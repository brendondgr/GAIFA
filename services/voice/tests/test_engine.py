"""The engine against a fake llama-server: load, unload, a size change, a child that dies, missing files."""

from __future__ import annotations

import dataclasses
import time

import pytest
from fastapi.testclient import TestClient

from voice.engine import Engine, EngineError
from voice.hub import Hub, HubError


async def test_load_and_unload(engine):
    st = await engine.load()
    assert st["state"] == "ready" and st["quant"] == "q4_k_m" and st["pid"] and st["port"]
    assert "-np" in engine.argv("q4_k_m", 1) and "--mmproj" in engine.argv("q4_k_m", 1)
    assert [m["loaded"] for m in engine.models()] == [True, False]
    pid = st["pid"]
    assert (await engine.load())["pid"] == pid            # already loaded: nothing restarts
    st = await engine.unload()
    assert st["state"] == "unloaded" and st["pid"] is None and not engine.alive()


async def test_a_size_change_replaces_the_child(engine):
    first = (await engine.load())["pid"]
    st = await engine.load("q8_0")
    assert st["quant"] == "q8_0" and st["pid"] != first and st["label"].endswith("Q8_0")
    engine.sessions = 1
    with pytest.raises(EngineError) as e:
        await engine.load("q4_k_m")
    assert e.value.code == "busy"
    engine.sessions = 0
    await engine.unload()


async def test_a_dead_child_is_started_again(engine):
    await engine.load()
    engine.proc.kill()
    await engine.proc.wait()
    assert engine.status()["state"] == "failed"
    port = await engine.ensure()
    assert engine.alive() and port == engine.port and engine.restarts == 1
    await engine.unload()


async def test_a_child_that_cannot_load(engine, monkeypatch):
    monkeypatch.setenv("FAKE_LLAMA_MODE", "die")
    with pytest.raises(EngineError) as e:
        await engine.load()
    assert e.value.code == "engine_failed" and "cannot load model" in e.value.detail
    assert engine.status()["state"] == "failed" and engine.status()["error"]


async def test_missing_files(engine, settings):
    settings.model_path("q8_0").unlink()
    with pytest.raises(EngineError) as e:
        await engine.load("q8_0")
    assert e.value.status == 409 and e.value.code == "model_missing" and "gaifa setup voice" in e.value.fix
    assert [m["present"] for m in engine.models()] == [True, False]
    gone = Engine(dataclasses.replace(settings, llama_bin=settings.llama_bin.with_name("nope")), Hub(""))
    with pytest.raises(EngineError) as e:
        await gone.load()
    assert e.value.code == "engine_missing"


async def test_memory_is_asked_for_first(engine):
    class NoRoom(Hub):
        async def acquire(self, gb, reason, make_room=False):
            raise HubError(409, "not enough free memory", "needs_room", {"plan": []})

    engine.hub = NoRoom("")
    with pytest.raises(HubError):
        await engine.load()
    assert not engine.alive() and engine.status()["state"] == "failed"


async def test_idle_unload(engine, settings):
    engine.settings = dataclasses.replace(settings, idle_unload_s=0.2)
    await engine.load()
    assert not await engine.idle_check()
    engine.last_used = time.time() - 1
    engine.sessions = 1
    assert not await engine.idle_check()                  # never under a conversation
    engine.sessions = 0
    assert await engine.idle_check() and engine.status()["state"] == "unloaded"


def test_routes(settings, tmp_path):
    from voice.server import create_app

    with TestClient(create_app(settings, log_dir=tmp_path / "logs")) as c:
        assert c.get("/health").json() == {"status": "ok"}
        st = c.get("/v1/status").json()
        assert st["loaded"] is False and st["sessions"] == 0 and len(st["models"]) == 2
        assert c.post("/v1/load", json={"quant": "q8_0"}).json()["quant"] == "q8_0"
        assert c.get("/v1/status").json()["loaded"] is True
        r = c.post("/v1/speech", json={"text": "hello"})
        assert r.status_code == 200 and r.content[:4] == b"RIFF"
        assert c.post("/v1/load", json={"quant": "q2"}).status_code == 422
        assert c.post("/v1/unload").json()["state"] == "unloaded"
        settings.mmproj_path.unlink()
        r = c.post("/v1/load")
        assert r.status_code == 409 and r.json()["code"] == "model_missing" and r.json()["data"]["fix"]
