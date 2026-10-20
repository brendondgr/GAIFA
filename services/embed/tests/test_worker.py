"""The model's worker process (with the fake backend): it loads, encodes, reloads with more encoders in the same
process, ends on unload, passes errors back, and a crash leaves the server up and the next call works."""

from __future__ import annotations

import os

import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient

from embed.encoder import Encoder, FakeBackend
from embed.hubclient import Hub
from embed.server import create_app
from embed.worker import WorkerBackend, WorkerDied

BATCH = {"text": 8}


class CrashingBackend(FakeBackend):
    """`crash` kills the worker the way a GPU segfault would; `boom` raises."""

    def encode(self, kind, items, batch_size):
        if any(str(x).endswith("crash") for x in items):
            os._exit(11)
        if any(str(x).endswith("boom") for x in items):
            raise ValueError("boom")
        return super().encode(kind, items, batch_size)


@pytest.fixture
def worker():
    w = WorkerBackend(CrashingBackend, timeout_s=60)
    yield w
    w.unload()


def test_load_encode_reload_unload(worker, tmp_path):
    enc = Encoder(worker, tmp_path)
    v = enc.embed([("text", "x: hello")], 768, BATCH)
    assert v.shape == (1, 768) and np.allclose(v[0], FakeBackend.vector("hello"))
    pid = worker.proc.pid
    assert pid != os.getpid() and worker.footprint_bytes() > 0
    enc.load(frozenset({"vision"}))
    assert worker.proc.pid == pid                       # more encoders: reloaded inside the same worker
    proc = worker.proc
    assert enc.unload() and not proc.is_alive() and not worker.alive


def test_errors_come_back_and_crashes_are_survived(worker, tmp_path):
    enc = Encoder(worker, tmp_path)
    with pytest.raises(ValueError, match="boom"):
        enc.embed([("text", "x: boom")], 768, BATCH)
    assert enc.loaded                                   # an error leaves the worker running
    with pytest.raises(WorkerDied, match="exit code 11"):
        enc.embed([("text", "x: crash")], 768, BATCH)
    assert not enc.loaded and not worker.alive
    assert enc.embed([("text", "x: again")], 768, BATCH).shape == (1, 768)     # a new worker


def test_server_answers_503_when_the_worker_dies(settings, hub):
    enc = Encoder(WorkerBackend(CrashingBackend), settings.state_dir)
    app = create_app(settings, encoder=enc, hub=Hub(settings.hub_url, transport=httpx.MockTransport(hub.handler)))
    with TestClient(app) as c:
        r = c.post("/v1/embed", json={"inputs": [{"text": "crash"}]})
        assert r.status_code == 503 and r.json()["code"] == "worker_died" and r.json()["fix"]
        assert c.get("/v1/status").json()["loaded"] is False
        assert c.post("/v1/embed", json={"inputs": [{"text": "fine"}]}).status_code == 200
