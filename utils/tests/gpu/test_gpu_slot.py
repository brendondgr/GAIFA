"""Plan 31.2: the reference client (`services/_template/gpu_slot.py`) against a hub app over ASGI: it waits,
renews, and releases on exit, on an exception and on task cancel. Every mod's copy is the same file."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path

import httpx
import pytest

from utils.tests.conftest import REPO

TEMPLATE = REPO / "services" / "_template" / "gpu_slot.py"
# Every Python mod that takes the slot keeps an identical copy (mods never import the hub or each other).
COPIES = [
    "services/comfy/comfy/gpu_slot.py", "services/gen3d/gen3d/gpu_slot.py", "services/tts/localtts/gpu_slot.py",
    "services/stt/stt/gpu_slot.py", "services/decide/decide/gpu_slot.py", "services/embed/embed/gpu_slot.py",
    "services/relay/web/backend/app/services/gpu_slot.py",
]


def load():
    spec = importlib.util.spec_from_file_location("gpu_slot_under_test", TEMPLATE)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod            # dataclasses look their module up
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def gs():
    return load()


def slot(gs, app, service: str, **kw):
    return gs.GpuSlot(hub_url="http://hub", service=service, transport=httpx.ASGITransport(app=app), **kw)


def held(app) -> list[str]:
    return [x.service for x in app.state.hub.gpu.held()]


async def test_waits_its_turn_then_runs(gs, app):
    order: list[str] = []
    waits: list[tuple] = []
    first_in = asyncio.Event()
    go = asyncio.Event()

    async def first():
        async with slot(gs, app, "comfy", poll_s=0.05).slot("image", est_s=30) as lease:
            assert lease.state == "granted" and lease.headers == {gs.HEADER: lease.id}
            first_in.set()
            order.append("comfy start")
            await go.wait()
            order.append("comfy end")

    async def second():
        await first_in.wait()

        def on_wait(lease):
            waits.append((lease.state, [a["service"] for a in lease.ahead], lease.eta_s))
            go.set()

        async with slot(gs, app, "gen3d", poll_s=0.05).slot("model", on_wait=on_wait) as lease:
            assert lease.state == "granted"
            order.append("gen3d start")

    await asyncio.wait_for(asyncio.gather(first(), second()), 5)
    assert order == ["comfy start", "comfy end", "gen3d start"]
    assert waits and waits[0][0] == "waiting" and waits[0][1] == ["comfy"]
    assert held(app) == []


async def test_renews_while_it_holds(gs, app):
    q = app.state.hub.gpu
    async with slot(gs, app, "comfy", renew_s=0.02).slot("image") as lease:
        before = q.leases[lease.id].renewed_ts
        await asyncio.sleep(0.15)
        assert q.leases[lease.id].renewed_ts > before


async def test_releases_on_exception(gs, app):
    with pytest.raises(RuntimeError):
        async with slot(gs, app, "comfy").slot("image"):
            assert held(app) == ["comfy"]
            raise RuntimeError("boom")
    assert held(app) == []
    assert app.state.hub.gpu.history[-1]["state"] == "released"


async def test_releases_on_cancel_while_holding_and_while_waiting(gs, app):
    entered = asyncio.Event()

    async def work():
        async with slot(gs, app, "comfy").slot("image"):
            entered.set()
            await asyncio.sleep(30)

    t = asyncio.create_task(work())
    await entered.wait()
    waiter = asyncio.create_task(_enter(slot(gs, app, "gen3d", poll_s=10).slot("model")))
    await asyncio.sleep(0.1)
    assert [x.service for x in app.state.hub.gpu.waiting()] == ["gen3d"]
    waiter.cancel()
    await asyncio.gather(waiter, return_exceptions=True)
    for _ in range(100):
        if not app.state.hub.gpu.waiting():
            break
        await asyncio.sleep(0.01)
    assert app.state.hub.gpu.waiting() == []
    t.cancel()
    await asyncio.gather(t, return_exceptions=True)
    assert held(app) == []


async def _enter(cm):
    async with cm:
        await asyncio.sleep(30)


async def test_cancel_from_the_queue_raises(gs, app):
    q = app.state.hub.gpu
    blocker = q.register("comfy", "job", "image")

    async def cancel_soon():
        for _ in range(200):
            if q.waiting():
                q.cancel(q.waiting()[0].id)
                return
            await asyncio.sleep(0.01)

    canceller = asyncio.create_task(cancel_soon())
    with pytest.raises(gs.GpuCancelled):
        async with slot(gs, app, "tts", poll_s=5).slot("speech"):
            pytest.fail("ran after a cancel")
    await canceller
    q.release(blocker.id)


async def test_nested_lease_through_parent(gs, app):
    async with slot(gs, app, "gen3d").slot("model") as outer:
        async with slot(gs, app, "comfy", poll_s=0.05).slot("trellis", parent=gs.lease_from(outer.headers)) as inner:
            assert inner.state == "granted"
            assert sorted(held(app)) == ["comfy", "gen3d"]


async def test_no_hub_runs_at_once(gs):
    async with gs.GpuSlot(hub_url="").slot("x") as lease:
        assert lease.state == "off" and lease.headers == {}
    async with gs.GpuSlot(hub_url="http://127.0.0.1:1").slot("x") as lease:    # unreachable
        assert lease.state == "off"


async def test_defaults_from_the_environment(gs, monkeypatch):
    monkeypatch.setenv("GAIFA_SERVICE_ID", "decide")
    monkeypatch.setenv("GAIFA_GPU_CLASS", "interactive")
    monkeypatch.setenv("GAIFA_GPU_GROUP", "decide-g")
    s = gs.GpuSlot(hub_url="http://hub")
    assert (s.service, s.cls, s.group) == ("decide", "interactive", "decide-g")


def test_waiting_text(gs):
    lease = gs.Lease(state="waiting", ahead=[{"service": "gen3d", "label": "is making a model", "eta_s": 240}], eta_s=240)
    assert lease.waiting_text({"gen3d": "3D Generate"}.get) == "Waiting for the GPU: 3D Generate is making a model (about 4 min)"


def test_every_copy_is_the_template():
    text = TEMPLATE.read_text()
    stale = [p for p in COPIES if (REPO / p).exists() and (REPO / p).read_text() != text]
    assert not stale, f"copy services/_template/gpu_slot.py over these: {stale}"
