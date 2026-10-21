"""Plan 31.3: `/v1/embed` and searches take an `interactive` GPU lease around the encode: they wait while another
mod holds the slot and run after; a lease cancelled from the queue answers 409; the lease is always released."""

from __future__ import annotations

import threading
import time

import httpx
from fastapi.testclient import TestClient

from embed.encoder import Encoder, FakeBackend
from embed.hubclient import Hub
from embed.server import create_app
from tests.conftest import FakeGpu


class GpuBackend(FakeBackend):
    device = "cuda"


def app_with(settings, hub, gpu: FakeGpu):
    enc = Encoder(GpuBackend(), settings.state_dir)
    return create_app(settings, encoder=enc, hub=Hub(settings.hub_url, transport=httpx.MockTransport(hub.handler)),
                      gpu=gpu.slot()), enc


def test_embed_waits_for_the_slot_then_runs(settings, hub):
    gpu = FakeGpu(blocked={"interactive"})
    app, enc = app_with(settings, hub, gpu)
    with TestClient(app) as c:
        out: dict = {}
        t = threading.Thread(target=lambda: out.update(r=c.post("/v1/embed", json={"inputs": [{"text": "hello"}]})))
        t.start()
        time.sleep(0.2)
        assert t.is_alive() and not enc.backend.batches          # waiting: nothing encoded
        gpu.blocked.clear()
        t.join(5)
    assert out["r"].status_code == 200, out["r"].text
    assert [e for e, _ in gpu.log] == ["wait", "granted", "released"]
    assert ("granted", "interactive") in gpu.log and not gpu.held


def test_a_cancelled_lease_is_a_409(settings, hub):
    gpu = FakeGpu(cancel_after=0)
    app, enc = app_with(settings, hub, gpu)
    with TestClient(app) as c:
        r = c.post("/v1/embed", json={"inputs": [{"text": "hello"}]})
    assert r.status_code == 409 and r.json()["code"] == "gpu_cancelled" and not enc.backend.batches


def test_the_lease_is_released_when_encoding_fails(settings, hub):
    class Broken(GpuBackend):
        def encode(self, *a, **k):
            raise FileNotFoundError("no weights")

    gpu = FakeGpu()
    enc = Encoder(Broken(), settings.state_dir)
    app = create_app(settings, encoder=enc, hub=Hub(settings.hub_url, transport=httpx.MockTransport(hub.handler)),
                     gpu=gpu.slot())
    with TestClient(app) as c:
        assert c.post("/v1/embed", json={"inputs": [{"text": "hello"}]}).status_code == 503
    assert gpu.log[-1][0] == "released" and not gpu.held
