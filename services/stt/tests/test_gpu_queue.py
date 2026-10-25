"""Plan 31.3: GAIFA's GPU slot. A file job waits (``waiting_gpu``) while another mod's work holds the GPU and
runs after; a cancel while it waits gives the lease back. Live dictation never waits: it runs on the CPU while
another mod holds the slot, and moves to the CPU when another mod's work starts waiting."""

from __future__ import annotations

import time

import httpx
import numpy as np
import pytest
from conftest import ALTERNATING, wait_job
from fakegpu import FakeGpu
from fastapi.testclient import TestClient

import stt.live
from stt.asr.mock import positional_audio
from stt.engine import Engine
from stt.gpu import Gpu
from stt.server import create_app
from test_transcribe_files import LocalHub


@pytest.fixture
def fake():
    return FakeGpu()


@pytest.fixture
def make(settings, fake):
    def build() -> TestClient:
        gpu = Gpu("http://hub", transport=httpx.ASGITransport(app=fake.app), poll_s=0.2)
        app = create_app(settings, engine=Engine(settings, gpu=True), hub=LocalHub({}), gpu=gpu)
        return TestClient(app)

    return build


def until(check, timeout: float = 10.0, every: float = 0.05):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        got = check()
        if got:
            return got
        time.sleep(every)
    raise AssertionError("timed out")


def upload(client) -> str:
    r = client.post("/v1/transcribe/upload", params={"filename": "a.wav", "save": "false"},
                    content=ALTERNATING.read_bytes())
    assert r.status_code == 202, r.text
    return r.json()["id"]


def test_a_job_waits_for_the_gpu_then_runs(make, fake):
    other = fake.hold("comfy", "portrait")
    with make() as client:
        jid = upload(client)
        job = until(lambda: (j := client.get(f"/v1/jobs/{jid}").json())["stage"] == "waiting_gpu" and j)
        assert job["state"] == "queued" and job["ahead"][0]["service"] == "comfy" and job["eta_s"] == 120
        st = client.get("/v1/status").json()
        row = next(j for j in st["jobs"] if j["id"] == jid)
        assert row["stage"] == "waiting_gpu" and row["ahead"][0]["service"] == "comfy"
        time.sleep(0.3)
        assert client.get(f"/v1/jobs/{jid}").json()["state"] == "queued"     # still waiting
        fake.release(other)
        done = wait_job(client, jid)
        assert done["state"] == "done", done
    assert ("granted", "stt", "job") in fake.log and ("released", "stt", "job") in fake.log
    assert not fake.held


def test_a_free_gpu_runs_the_job_at_once_and_gives_it_back(make, fake):
    with make() as client:
        assert wait_job(client, upload(client))["state"] == "done"
    assert [e for e in fake.log if e[1] == "stt"] == [("granted", "stt", "job"), ("released", "stt", "job")]


def test_cancelling_a_job_that_waits_gives_its_place_back(make, fake):
    fake.hold("comfy")
    with make() as client:
        jid = upload(client)
        until(lambda: client.get(f"/v1/jobs/{jid}").json()["stage"] == "waiting_gpu")
        assert client.post(f"/v1/jobs/{jid}/cancel").json()["state"] == "cancelled"
        until(lambda: not any(w["service"] == "stt" for w in fake.waiting))
        assert ("released", "stt", "job") in fake.log


def test_a_job_cancelled_in_the_queue_is_cancelled(make, fake):
    fake.hold("comfy")
    with make() as client:
        jid = upload(client)
        until(lambda: client.get(f"/v1/jobs/{jid}").json()["stage"] == "waiting_gpu")
        fake.waiting = [w for w in fake.waiting if w["service"] != "stt"]      # the queue's Cancel
        job = until(lambda: (j := client.get(f"/v1/jobs/{jid}").json())["state"] == "cancelled" and j)
        assert "GPU queue" in job["error"]


def test_a_cpu_engine_takes_no_slot(settings, fake):
    gpu = Gpu("http://hub", transport=httpx.ASGITransport(app=fake.app), poll_s=0.2)
    fake.hold("comfy")
    with TestClient(create_app(settings, hub=LocalHub({}), gpu=gpu)) as client:     # settings.device = cpu
        assert wait_job(client, upload(client))["state"] == "done"
    assert not [e for e in fake.log if e[1] == "stt"]


# -- live dictation -------------------------------------------------------------------------------------

def frames(ws, audio: np.ndarray, step: int = 1600) -> None:
    for i in range(0, audio.size, step):
        ws.send_bytes(audio[i:i + step].astype("<f4").tobytes())


def finish(ws) -> list[dict]:
    ws.send_json({"type": "stop"})
    out = []
    while True:
        ev = ws.receive_json()
        out.append(ev)
        if ev["type"] in ("done", "error"):
            return out


def test_dictation_runs_on_the_cpu_while_another_mod_holds_the_gpu(make, fake):
    fake.hold("comfy", "portrait")
    with make() as client:
        with client.websocket_connect("/v1/stream") as ws:
            ws.send_json({"type": "start", "preset": "accurate", "encoding": "float32"})
            ready = ws.receive_json()
            assert ready["type"] == "ready" and ready["device"] == "cpu" and ready["model"] == "small"
            assert "Comfy (portrait) is using the GPU" in ready["reason"]
            frames(ws, positional_audio(0.0, 4.0))
            assert finish(ws)[-1]["type"] == "done"
    assert not [e for e in fake.log if e[1] == "stt"]       # it never asked for the slot


def test_dictation_holds_the_slot_and_gives_it_back_when_others_wait(make, fake, monkeypatch):
    monkeypatch.setattr(stt.live, "WATCH_S", 0.05)
    with make() as client:
        with client.websocket_connect("/v1/stream") as ws:
            ws.send_json({"type": "start", "preset": "fast", "encoding": "float32"})
            ready = ws.receive_json()
            assert ready["device"] == "cuda" and "reason" not in ready
            assert ("granted", "stt", "interactive") in fake.log
            audio = positional_audio(0.0, 6.0)
            frames(ws, audio[:16000])
            fake.wait_other("comfy")
            # the CPU model loads while the GPU keeps serving; then the next frame moves the stream
            until(lambda: client.get("/v1/status").json()["cpu_engine"] and
                  client.get("/v1/status").json()["cpu_engine"]["leases"])
            ws.send_bytes(audio[16000:17600].astype("<f4").tobytes())
            ev = ws.receive_json()
            while ev["type"] in ("hypothesis", "committed"):     # what the first second said
                ev = ws.receive_json()
            assert ev["type"] == "device" and ev["device"] == "cpu" and "Comfy" in ev["reason"]
            until(lambda: ("released", "stt", "interactive") in fake.log)
            assert client.get("/v1/status").json()["streams"][0]["device"] == "cpu"
            frames(ws, audio[17600:])
            assert finish(ws)[-1]["type"] == "done"
        assert client.get("/v1/status").json()["streams"] == []


def test_dictation_on_the_gpu_releases_the_slot_when_it_ends(make, fake):
    with make() as client:
        with client.websocket_connect("/v1/stream") as ws:
            ws.send_json({"type": "start", "preset": "fast", "encoding": "float32"})
            assert ws.receive_json()["device"] == "cuda"
            frames(ws, positional_audio(0.0, 2.0))
            finish(ws)
        until(lambda: ("released", "stt", "interactive") in fake.log)
    assert not fake.held
