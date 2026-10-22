"""Plan 31.3: each ask takes an `interactive` GPU lease around the model call (slot first, then memory), waits
while another mod holds the slot, gives it back on failure, and skips the slot on the CPU."""

from __future__ import annotations

import asyncio
import json
import threading
import time

import httpx
from fastapi.testclient import TestClient

from decide.engine import Decider, LocalBackend
from decide.gpu_slot import GpuSlot
from decide.hubclient import Hub
from decide.models.fake import FakeModel
from decide.server import create_app


class GpuFake(FakeModel):
    def __init__(self) -> None:
        super().__init__()
        self.device = "cuda"


class FakeGpu:
    """/api/gpu/*: while `busy` (another mod holds the slot) acquire answers 202 after a short wait."""

    def __init__(self, hub) -> None:
        self.hub, self.busy = hub, False
        self.log: list[tuple[str, str]] = []        # (what, lease or class)
        self.held: set[str] = set()

    async def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if not path.startswith("/api/gpu"):
            if path == "/api/memory/acquire":
                self.log.append(("memory", ""))
            return self.hub.handler(request)
        body = json.loads(request.content or b"{}")
        if path == "/api/gpu/acquire":
            if self.busy:
                self.log.append(("wait", body["class"]))
                await asyncio.sleep(0.02)
                return httpx.Response(202, json={"lease": body["lease"], "state": "waiting", "eta_s": 60,
                                                 "ahead": [{"id": "gl_x", "service": "comfy", "label": "image", "state": "held", "eta_s": 60}]})
            self.held.add(body["lease"])
            self.log.append(("granted", body["class"]))
            return httpx.Response(200, json={"lease": body["lease"], "state": "granted"})
        lid = path.split("/")[3]
        if path.endswith("/release"):
            self.held.discard(lid)
            self.log.append(("released", lid))
        return httpx.Response(200, json={"lease": lid, "state": "granted"})


def make(settings, hub, model=GpuFake, device="auto", adapters=None):
    gpu = FakeGpu(hub)
    transport = httpx.MockTransport(gpu.handler)
    settings.device = device
    adapters = adapters or {"fake": model}
    dec = Decider(LocalBackend(adapters, settings.models_dir), settings.state_dir)
    h = Hub(settings.hub_url, transport=transport)
    app = create_app(settings, decider=dec, hub=h, adapters=adapters,
                     gpu=GpuSlot(hub_url="http://hub", service="decide", cls="interactive", transport=transport, poll_s=0.05))
    return app, gpu, dec


ASK = {"input": "The parcel arrived broken.", "questions": [{"id": "q", "type": "yesno", "question": "Broken?"}]}


def test_an_ask_waits_for_the_slot_and_runs_after(settings, hub):
    app, gpu, _ = make(settings, hub)
    gpu.busy = True
    with TestClient(app) as c:
        out: dict = {}
        t = threading.Thread(target=lambda: out.update(r=c.post("/v1/decide", json=ASK)))
        t.start()
        time.sleep(0.2)
        assert t.is_alive() and not FakeModel.calls            # waiting: the model wasn't asked
        gpu.busy = False
        t.join(5)
        assert out["r"].status_code == 200, out["r"].text
    kinds = [k for k, _ in gpu.log]
    assert kinds[0] == "wait" and "granted" in kinds and kinds[-1] == "released"
    assert ("granted", "interactive") in gpu.log
    assert gpu.held == set()


def test_slot_before_memory_when_switching_models(settings, hub):
    class Other(GpuFake):
        ID = "other"

    app, gpu, dec = make(settings, hub, adapters={"fake": GpuFake, "other": Other})
    with TestClient(app) as c:
        assert c.post("/v1/decide", json=ASK).status_code == 200
        gpu.log.clear()
        assert c.post("/v1/decide", json={**ASK, "model": "other"}).status_code == 200
    assert [k for k, _ in gpu.log] == ["granted", "memory", "released"]     # memory is asked for inside the slot


def test_released_when_the_model_fails(settings, hub):
    class Broken(GpuFake):
        def ask(self, *a, **k):
            raise RuntimeError("the worker died")

    app, gpu, _ = make(settings, hub, model=Broken)
    with TestClient(app) as c:
        r = c.post("/v1/decide", json=ASK)
    assert r.status_code == 503
    assert gpu.held == set() and gpu.log[-1][0] == "released"


def test_cpu_skips_the_slot(settings, hub):
    app, gpu, _ = make(settings, hub, model=FakeModel, device="cpu")
    gpu.busy = True                                             # would wait forever if it asked
    with TestClient(app) as c:
        assert c.post("/v1/decide", json=ASK).status_code == 200
    assert not [k for k, _ in gpu.log if k != "memory"]


def test_answer_within_counts_from_the_slot(settings, hub):
    """X-AIHub-Answer-Within: waiting for the GPU doesn't use the budget; a slow model past it answers 504, and the
    slot is held until the model is done."""
    class Slow(GpuFake):
        def ask(self, *a, **k):
            time.sleep(0.6)
            return super().ask(*a, **k)

    app, gpu, _ = make(settings, hub)
    gpu.busy = True
    with TestClient(app) as c:
        out: dict = {}
        t = threading.Thread(target=lambda: out.update(r=c.post("/v1/decide", json=ASK, headers={"X-AIHub-Answer-Within": "0.3"})))
        t.start()
        time.sleep(0.5)                                         # longer than the budget, all of it waiting
        gpu.busy = False
        t.join(5)
        assert out["r"].status_code == 200, out["r"].text

    app, gpu, _ = make(settings, hub, model=Slow)
    with TestClient(app) as c:
        r = c.post("/v1/decide", json=ASK, headers={"X-AIHub-Answer-Within": "0.2"})
        assert r.status_code == 504 and r.json()["code"] == "answer_timeout"
        assert gpu.held                                         # still running: the slot stays held
        for _ in range(100):
            if not gpu.held:
                break
            time.sleep(0.02)
        assert gpu.held == set()
