"""Leases: an open live stream or a running file job keeps its model. The idle unloader leaves it,
another model is refused (or, for a queued job, waited for), and a model unloaded anyway is loaded
again on the next pass instead of failing the stream."""

from __future__ import annotations

import asyncio
import dataclasses
import time

import numpy as np
import pytest
from conftest import ALTERNATING, wait_job
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from stt.asr.mock import positional_audio
from stt.engine import Engine, ModelBusy
from stt.server import create_app
from test_transcribe_files import LocalHub


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings, hub=LocalHub({}))) as c:
        yield c


def send(ws, samples: np.ndarray, step: int = 1600) -> None:
    for i in range(0, samples.size, step):
        ws.send_bytes(samples[i:i + step].astype("<f4").tobytes())


def finish(ws) -> dict:
    ws.send_json({"type": "stop"})
    while True:
        ev = ws.receive_json()
        if ev["type"] in ("done", "error"):
            return ev


def test_a_stream_keeps_going_when_its_model_is_unloaded_midway(client):
    audio = positional_audio(0.0, 20.0)
    with client.websocket_connect("/v1/stream") as ws:
        ws.send_json({"type": "start", "preset": "fast", "encoding": "float32"})
        assert ws.receive_json()["type"] == "ready"
        send(ws, audio[:audio.size // 2])
        assert client.post("/v1/unload").json()["state"] == "unloaded"      # the user's Unload button
        send(ws, audio[audio.size // 2:])
        done = finish(ws)
    assert done["type"] == "done", done
    assert len(done["text"].split()) > 30 and done["duration"] == 20.0
    assert client.get("/v1/models").json()["engine"]["model"] == "base"      # loaded again, the same one


def test_the_idle_unloader_leaves_a_leased_model_through_silence(settings):
    engine = Engine(dataclasses.replace(settings, idle_unload_s=0.01))

    async def scenario() -> tuple[bool, bool]:
        await engine.acquire("base")
        engine.last_used = time.monotonic() - 600                 # five minutes of a silent stream
        loop = asyncio.create_task(engine.idle_loop(interval=0.01))
        await asyncio.sleep(0.2)
        held = engine.ready
        engine.release("base")
        engine.last_used = time.monotonic() - 600
        await asyncio.sleep(0.2)
        loop.cancel()
        released = engine.ready
        await engine.unload()
        return held, released

    held, released = asyncio.run(scenario())
    assert held is True and released is False


def test_another_model_is_refused_while_a_stream_holds_one(client):
    with client.websocket_connect("/v1/stream") as ws:
        ws.send_json({"type": "start", "preset": "fast"})
        assert ws.receive_json()["type"] == "ready"
        st = client.get("/v1/status").json()
        assert st["busy"] is True and st["engine"]["leases"] == {"base": 1}   # the hub won't unload a busy mod

        r = client.post("/v1/load", json={"model": "small"})
        assert r.status_code == 409 and r.json()["code"] == "busy" and "base" in r.json()["fix"]
        with client.websocket_connect("/v1/stream") as other:
            other.send_json({"type": "start", "preset": "balanced"})
            err = other.receive_json()
            assert err["code"] == "busy" and "base" in err["detail"]
            with pytest.raises(WebSocketDisconnect) as closed:
                other.receive_json()
            assert closed.value.code == 4409
        assert client.post("/v1/load", json={"model": "base"}).status_code == 200   # the same one is fine
        assert finish(ws)["type"] == "done"
    assert client.get("/v1/status").json()["engine"]["leases"] == {}
    assert client.post("/v1/load", json={"model": "small"}).json()["model"] == "small"


def test_a_file_job_waits_for_a_stream_on_another_model(client):
    with client.websocket_connect("/v1/stream") as ws:
        ws.send_json({"type": "start", "preset": "fast", "encoding": "float32"})
        assert ws.receive_json()["type"] == "ready"
        r = client.post("/v1/transcribe/upload", params={"filename": "a.wav", "save": "false"},
                        content=ALTERNATING.read_bytes())
        jid = r.json()["id"]
        deadline = time.monotonic() + 10
        while (job := client.get(f"/v1/jobs/{jid}").json())["stage"] != "waiting":
            assert time.monotonic() < deadline and job["state"] in ("queued", "running"), job
            time.sleep(0.02)
        send(ws, positional_audio(0.0, 4.0))                     # the stream still runs on its model
        assert client.get("/v1/status").json()["engine"]["model"] == "base"
        assert finish(ws)["model"] == "base"
    job = wait_job(client, jid)
    assert job["state"] == "done" and job["model"] == "small"


def test_a_lease_holder_loads_its_model_again_after_an_unload(settings):
    engine = Engine(settings)

    async def scenario() -> str | None:
        await engine.acquire("base")
        await engine.unload()
        await asyncio.to_thread(engine.transcribe, positional_audio(0.0, 2.0), model="base")
        model = engine.model
        with pytest.raises(ModelBusy):
            await engine.ensure("small")
        engine.release("base")
        await engine.unload()
        return model

    assert asyncio.run(scenario()) == "base"
