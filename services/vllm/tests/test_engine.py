"""The engine's lifecycle against the fake vLLM and a fake hub (plan 18.2)."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from vllm_mod.engine import Engine, EngineError, next_stage
from vllm_mod.hubclient import NeedsRoom
from vllm_mod.server import create_app

from .conftest import run


async def _models(e: Engine) -> list[str]:
    r = await e.http.get("/v1/models")
    return [m["id"] for m in r.json()["data"]]


async def _until(cond, timeout: float = 10.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not cond():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("timed out")
        await asyncio.sleep(0.05)


def test_load_and_unload(make_engine, hub, settings):
    async def go():
        e = make_engine()
        v = await e.load("small")
        assert v["state"] == "ready" and v["profile"] == "small" and v["endpoint"].endswith(f":{settings.engine_port}/v1")
        assert await _models(e) == ["small"]
        assert hub.calls == [{"service": "vllm", "needs_bytes": 3 * 10**9, "reason": "vLLM Small", "make_room": None}]
        assert json.loads((settings.state_dir / "last.json").read_text()) == {"profile": "small"}
        assert any("Loading weights" in ln for ln in e.lines)
        assert "--served-model-name" in v["command"]
        assert (await e.unload())["state"] == "unloaded"
        assert await e.c.list() == []
        with pytest.raises(httpx.HTTPError):
            await e.http.get("/health")
        await e.shutdown()
    run(go())


def test_load_without_a_profile_uses_the_last_one(make_engine, settings):
    (settings.state_dir).mkdir(parents=True)
    (settings.state_dir / "last.json").write_text('{"profile": "big"}')

    async def go():
        e = make_engine()
        assert e.default_profile().id == "big"
        assert (await e.load(wait=False))["profile"] == "big"
        await e.shutdown()
    run(go())


def test_switching_profiles_stops_the_first(make_engine):
    async def go():
        e = make_engine()
        await e.load("small")
        await e.load("big", make_room=True)
        assert [(f.name, f.running) for f in await e.c.list()] == [("gaifa-vllm-big", True)]
        assert await _models(e) == ["big"]
        await e.shutdown()
        assert await e.c.list() == []
    run(go())


def test_a_second_load_of_the_same_profile_waits_for_the_first(make_engine, hub):
    async def go():
        e = make_engine()
        a, b = await asyncio.gather(e.load("small"), e.load("small"))
        assert a["state"] == b["state"] == "ready" and len(hub.calls) == 1
        await e.shutdown()
    run(go())


def test_adoption_after_an_adapter_crash(make_engine):
    async def go():
        first = make_engine()
        await first.load("small")
        await first.shutdown(stop_engine=False)          # as if the adapter died
        second = make_engine()
        await second.adopt()
        await _until(lambda: second.state == "ready")
        assert second.profile.id == "small" and await _models(second) == ["small"]
        await second.shutdown()
        assert await second.c.list() == []
    run(go())


def test_adoption_removes_exited_and_unknown_engines(make_engine, settings):
    async def go():
        first = make_engine()
        await first.load("small")
        await first.shutdown(stop_engine=False)
        (settings.profiles_dir / "small.toml").unlink()     # its profile is gone
        second = make_engine()
        await second.adopt()
        assert second.state == "unloaded" and await second.c.list() == []
    run(go())


def test_a_crash_while_serving_fails_with_the_log(make_engine, monkeypatch):
    monkeypatch.setenv("FAKE_VLLM_CRASH_S", "0.5")

    async def go():
        e = make_engine()
        await e.load("small")
        await _until(lambda: e.state == "failed")
        assert "while serving" in e.error and "illegal memory access" in e.last_error
        assert await e.c.list() == []
        assert (await e.unload())["state"] == "unloaded"
    run(go())


def test_a_failed_start_raises_with_the_log(make_engine, monkeypatch):
    monkeypatch.setenv("FAKE_VLLM_FAIL", "1")

    async def go():
        e = make_engine()
        with pytest.raises(EngineError) as ei:
            await e.load("small")
        assert ei.value.code == "start_failed" and "No HIP GPUs" in "\n".join(ei.value.data["log"])
        assert e.state == "failed" and await e.c.list() == []
    run(go())


def test_needs_room_starts_nothing(make_engine, hub):
    hub.room = False

    async def go():
        e = make_engine()
        with pytest.raises(NeedsRoom) as ei:
            await e.load("big")
        assert ei.value.body["code"] == "needs_room" and ei.value.body["data"]["plan"]["needs_bytes"] == 31 * 10**9
        assert e.state == "unloaded" and e.profile is None and await e.c.list() == []
    run(go())


def test_startup_timeout(make_engine, settings, monkeypatch):
    monkeypatch.setenv("FAKE_VLLM_STARTUP_S", "30")
    settings.start_timeout_s = 1

    async def go():
        e = make_engine()
        with pytest.raises(EngineError, match="wasn't healthy after 1s"):
            await e.load("small")
        assert await e.c.list() == []
    run(go())


def test_stages_only_move_forward():
    s = next_stage("starting container", "INFO Starting to load model org/x")
    assert s == "loading weights"
    s = next_stage(s, "Capturing CUDA graphs (PIECEWISE): 25%")
    assert s == "capturing graphs"
    assert next_stage(s, "Loading weights took 0.1 s") == "capturing graphs"
    # eager mode announces what it turns off; that isn't a stage
    s = next_stage("initializing", "WARNING Enforce eager set, disabling torch.compile, CUDAGraphs, and JIT kernel warmup.")
    assert s == "initializing"
    assert next_stage("loading weights", "INFO Model loading took 22.87 GiB memory and 17.0 seconds") == "profiling"


def test_routes(settings, make_engine, make_downloads, hub):
    eng = make_engine()
    app = create_app(settings, engine=eng, downloads=make_downloads(eng))
    with TestClient(app) as c:
        r = c.post("/v1/load", json={"profile": "nope"})
        assert r.status_code == 404 and r.json()["code"] == "not_found" and "small" in r.json()["data"]["profiles"]
        hub.room = False
        r = c.post("/v1/load", json={"profile": "small"})
        assert r.status_code == 409 and r.json()["code"] == "needs_room"
        hub.room = True
        r = c.post("/v1/load", json={"profile": "small"}, headers={"X-GAIFA-Make-Room": "1"})
        assert r.status_code == 200 and r.json()["state"] == "ready"
        assert hub.calls[-1]["make_room"] == "1"
        st = c.get("/v1/status").json()
        assert st["loaded"] is True and st["memory_estimate_gb"] == 3
        assert c.get("/v1/profiles").json()["loaded"] == "small"
        assert c.get("/v1/engine/logs", params={"tail": 5}).json()["lines"]
        assert c.post("/v1/unload").json()["state"] == "unloaded"
        assert c.get("/v1/status").json()["loaded"] is False
