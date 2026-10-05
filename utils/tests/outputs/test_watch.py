"""4.2: the watcher indexes new outputs live, waits for files to settle, and reconciles at startup."""

from __future__ import annotations

import asyncio
import json
import shutil
import time

import pytest

from utils.events import Alerts
from utils.outputs.watch import ALERT, Watcher
from utils.tests.outputs.conftest import drain
from utils.tests.services.conftest import until


@pytest.fixture
async def watch(outs, bus):
    alerts = Alerts(bus)
    w = Watcher(outs, alerts, stable_s=0.25, debounce_ms=100, retry_s=0.2)
    w.alerts_ = alerts
    w.start()
    await asyncio.wait_for(w.ready.wait(), 5)
    await asyncio.sleep(0.2)  # inotify watches are in place
    yield w
    await w.close()


def outputs_events(sub) -> list[dict]:
    return [e for e in drain(sub) if e["type"] in ("output", "output_deleted")]


async def count(outs) -> int:
    return (await outs.list())["totals"]["count"]


async def test_part_then_rename(watch, outs, tree, bus):
    sub = bus.subscribe()
    part = tree.put("svc/2026-10-04/120000-hello.txt.part", "hello")
    await asyncio.sleep(0.8)
    assert await count(outs) == 0  # a .part file is never an output
    t0 = time.monotonic()
    part.rename(part.with_name("120000-hello.txt"))
    await until(lambda: any(e["type"] == "output" for e in list(sub.queue._queue)), timeout=5)
    assert time.monotonic() - t0 < 2
    ev = outputs_events(sub)
    assert [e["type"] for e in ev] == ["output"] and ev[0]["output"]["title"] == "hello"


async def test_a_folder_appears_once_complete(watch, outs, tree, bus):
    sub = bus.subscribe()
    d = tree.folder("gen3d/2026-10-04/j1-fox", {"mesh.glb": 50, "parts/p0.glb": 5}, complete=False, title="fox")
    await asyncio.sleep(0.8)
    assert await count(outs) == 0  # nothing inside an incomplete folder output is indexed
    (d / "rigged.glb").write_bytes(b"\0" * 60)
    (d / "output.json").write_text(json.dumps({"complete": True, "title": "fox"}))
    await until(lambda: any(e["type"] == "output" for e in list(sub.queue._queue)), timeout=5)
    await asyncio.sleep(0.5)
    ev = outputs_events(sub)
    assert [e["type"] for e in ev] == ["output"]
    o = ev[0]["output"]
    assert (o["title"], o["kind"], len(o["files"]), o["size_bytes"]) == ("fox", "model3d", 3, 115)


async def test_a_growing_file_waits_until_it_settles(watch, outs, tree, bus):
    sub = bus.subscribe()
    p = tree.dir / "comfy/2026-10-04/ComfyUI_00001_.mp4"
    p.parent.mkdir(parents=True)
    with p.open("wb") as f:
        for _ in range(8):  # written for ~0.8 s, longer than stable_s
            f.write(b"\0" * 1000)
            f.flush()
            await asyncio.sleep(0.1)
    await until(lambda: any(e["type"] == "output" for e in list(sub.queue._queue)), timeout=5)
    await asyncio.sleep(0.6)
    ev = outputs_events(sub)
    assert [e["type"] for e in ev] == ["output"] and ev[0]["output"]["size_bytes"] == 8000


async def test_deletes(watch, outs, tree, bus):
    tree.put("svc/2026-10-04/a.txt", "a")
    tree.put("svc/2026-10-04/b.txt", "b")
    tree.put("svc/2026-10-05/c.txt", "c")
    await until(lambda: watch.pending == {} and not watch._dirty, timeout=5)
    await until_count(outs, 3)
    sub = bus.subscribe()
    (tree.dir / "svc/2026-10-04/a.txt").unlink()
    await until_count(outs, 2)
    shutil.rmtree(tree.dir / "svc")
    await until_count(outs, 0)
    assert sorted(e["type"] for e in outputs_events(sub)) == ["output_deleted"] * 3


async def until_count(outs, n: int, timeout: float = 5) -> None:
    deadline = time.monotonic() + timeout
    while (c := await count(outs)) != n:
        if time.monotonic() > deadline:
            raise AssertionError(f"{c} outputs, expected {n}")
        await asyncio.sleep(0.05)


async def test_startup_reconcile_without_an_event_per_output(outs, tree, bus, db):
    tree.put("svc/2026-10-04/keep.txt", "k")
    tree.put("svc/2026-10-04/gone.txt", "g")
    await outs.sync(publish=False)
    (tree.dir / "svc/2026-10-04/gone.txt").unlink()
    for i in range(60):  # written while the hub was down
        tree.put(f"svc/2026-10-05/{i:03d}.txt", "n")
    sub = bus.subscribe()
    w = Watcher(outs, stable_s=0.25, debounce_ms=100)
    w.start()
    try:
        await asyncio.wait_for(w.ready.wait(), 10)
        assert await count(outs) == 61
        assert outputs_events(sub) == [{"type": "output_deleted", "id": "*"}]  # pages refetch once
    finally:
        await w.close()
    rows = await db.fetchall("SELECT path FROM outputs")
    assert "svc/2026-10-04/gone.txt" not in {r["path"] for r in rows}


async def test_reconcile_with_nothing_changed_is_quiet(outs, tree, bus):
    tree.put("svc/a.txt", "a")
    await outs.sync(publish=False)
    sub = bus.subscribe()
    assert await outs.reconcile() == 0
    assert outputs_events(sub) == []


async def test_recovers_when_outputs_is_removed(watch, outs, tree, bus):
    tree.put("svc/2026-10-04/a.txt", "a")
    await until_count(outs, 1)
    shutil.rmtree(tree.dir)
    await until(lambda: ALERT in {a["id"] for a in watch.alerts_.list()}, timeout=5)
    await until(lambda: tree.dir.is_dir(), timeout=5)  # recreated by the watcher
    await until(lambda: ALERT not in {a["id"] for a in watch.alerts_.list()}, timeout=5)
    await until_count(outs, 0)  # the full rescan after recovering drops what vanished
    await asyncio.sleep(0.3)
    tree.put("svc/2026-10-04/b.txt", "b")
    await until_count(outs, 1)


async def test_close_is_quick(outs):
    w = Watcher(outs)
    w.start()
    await asyncio.wait_for(w.ready.wait(), 5)
    t0 = time.monotonic()
    await w.close()
    assert time.monotonic() - t0 < 1.5


async def test_a_mods_output_appears_live_through_the_hub(services_dir, make_app):
    """Phase 4 check: calling fake-ok's output route shows the file within 2 s, with no reload."""
    import httpx

    from utils.tests.models.test_used_by import with_dirs

    services = services_dir("fake-ok")
    with_dirs(services, "fake-ok", [])  # a free port
    app = make_app(port=7000, autostart=False)
    async with app.router.lifespan_context(app):
        hub = app.state.hub
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://hub") as c:
            assert (await c.post("/api/services/fake-ok/start", params={"wait": 1})).json()["state"] == "ready"
            await asyncio.sleep(0.3)  # the startup rescan is done and outputs/fake-ok is watched
            sub = hub.bus.subscribe()
            t0 = time.monotonic()
            r = await c.post("/api/s/fake-ok/v1/outputs", json={"text": "hello from fake"})
            assert r.status_code == 201
            ev = await asyncio.wait_for(_first(sub, "output"), 2)
            assert time.monotonic() - t0 < 2
            o = ev["output"]
            assert (o["service"], o["kind"], o["title"]) == ("fake-ok", "text", "hello from fake")
            assert o["meta"]["prompt"] == "hello from fake" and o["path"].startswith("outputs/fake-ok/")
            assert (await c.get(o["url"])).text == "hello from fake"
            page = (await c.get("/api/outputs", params={"service": "fake-ok"})).json()
            assert [x["id"] for x in page["items"]] == [o["id"]]
            await until(lambda: any(a["text"] == 'Fake OK created "hello from fake"' for a in hub.activity.recent()), timeout=5)
            await c.post("/api/services/fake-ok/stop", params={"wait": 1})


async def _first(sub, kind: str) -> dict:
    while True:
        ev = await sub.get()
        if ev["type"] == kind:
            return ev
