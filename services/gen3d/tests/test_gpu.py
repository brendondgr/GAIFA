"""Plan 31.3: a job takes GAIFA's GPU slot (a fake hub) before its first stage, holds it across its stages,
waits (queued, stage waiting_gpu) while another mod holds it, and passes its lease to comfy."""

import asyncio
import json
import threading
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from gen3d.comfy_engine import ComfyEngine
from gen3d.gpu_slot import GpuSlot, Lease
from gen3d.server import app
from test_comfy_engine import Hub as ComfyHub, run as comfy_run


class FakeGpu:
    """/api/gpu/*: grants at once unless `busy` (another mod holds the slot)."""

    def __init__(self):
        self.busy = False
        self.acquires, self.released, self.held = [], [], set()
        self.lock = threading.Lock()

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        p = request.url.path
        if p == "/api/gpu/acquire" and self.busy:
            await asyncio.sleep(0.02)              # the hub's long poll (?wait=): the caller yields meanwhile
        with self.lock:
            if p == "/api/gpu/acquire":
                body = json.loads(request.content)
                self.acquires.append(body)
                if self.busy:
                    return httpx.Response(202, json={"lease": body["lease"], "state": "waiting", "eta_s": 120,
                                                     "ahead": [{"id": "gl_c", "service": "comfy", "label": "an image",
                                                                "state": "held", "eta_s": 120}]})
                self.held.add(body["lease"])
                return httpx.Response(200, json={"lease": body["lease"], "state": "granted"})
            if p.endswith("/renew"):
                return httpx.Response(200, json={"lease": p.split("/")[3], "state": "granted"})
            if p.endswith("/release"):
                lease = p.split("/")[3]
                self.released.append(lease)
                self.held.discard(lease)
                return httpx.Response(200, json={"lease": lease, "state": "released"})
        return httpx.Response(404, json={"detail": p})


@pytest.fixture
def env():
    gpu = FakeGpu()
    with TestClient(app) as c:
        c.app.state.runner.gpu = GpuSlot(hub_url="http://hub", service="gen3d", transport=httpx.MockTransport(gpu),
                                         poll_s=0.02, renew_s=0.05)
        yield c, gpu


def until(cond, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return cond()


def test_a_job_waits_for_the_slot_then_runs(env):
    c, gpu = env
    gpu.busy = True
    job = c.post("/v1/jobs", json={"prompt": "a chair", "stages": ["shape"]}).json()
    assert until(lambda: c.get(f"/v1/jobs/{job['id']}").json().get("stage") == "waiting_gpu")
    j = c.get(f"/v1/jobs/{job['id']}").json()
    assert j["status"] == "queued" and j["ahead"][0]["service"] == "comfy" and j["eta_s"] == 120
    assert j["stages"]["shape"]["state"] == "pending"                  # nothing ran
    st = next(x for x in c.get("/v1/status").json()["jobs"] if x["id"] == job["id"])
    assert st["state"] == "queued" and st["stage"] == "waiting_gpu"
    gpu.busy = False
    assert until(lambda: c.get(f"/v1/jobs/{job['id']}").json()["status"] == "done")
    assert "stage" not in c.get(f"/v1/jobs/{job['id']}").json()
    leases = [a["lease"] for a in gpu.acquires]
    assert len(set(leases)) == 1 and gpu.acquires[0]["service"] == "gen3d" and gpu.acquires[0]["class"] == "job"
    assert until(lambda: leases[0] in gpu.released)


def test_one_lease_across_all_stages(env):
    c, gpu = env
    job = c.post("/v1/jobs", json={"prompt": "a stool", "stages": ["shape", "parts", "preview"],
                                   "parts": {"parts": ["seat", "legs"]}}).json()
    assert until(lambda: c.get(f"/v1/jobs/{job['id']}").json()["status"] == "done")
    assert len({a["lease"] for a in gpu.acquires}) == 1
    assert until(lambda: gpu.released == [gpu.acquires[0]["lease"]])


def test_cancel_while_waiting_releases_and_the_runner_goes_on(env):
    c, gpu = env
    gpu.busy = True
    job = c.post("/v1/jobs", json={"prompt": "never", "stages": ["shape"]}).json()
    assert until(lambda: c.get(f"/v1/jobs/{job['id']}").json().get("stage") == "waiting_gpu")
    lease = gpu.acquires[-1]["lease"]
    assert c.post(f"/v1/jobs/{job['id']}/cancel").json()["status"] == "canceled"
    assert until(lambda: lease in gpu.released)
    gpu.busy = False
    nxt = c.post("/v1/jobs", json={"prompt": "next", "stages": ["shape"]}).json()
    assert until(lambda: c.get(f"/v1/jobs/{nxt['id']}").json()["status"] == "done")
    assert c.get(f"/v1/jobs/{job['id']}").json()["status"] == "canceled"


def test_a_failed_job_releases(env):
    c, gpu = env
    r = c.post("/v1/jobs", json={"stages": ["parts"], "parts": {"parts": ["a"]}}).json()    # no mesh to split: fails
    assert until(lambda: c.get(f"/v1/jobs/{r['id']}").json()["status"] == "failed")
    assert until(lambda: gpu.acquires and gpu.acquires[-1]["lease"] in gpu.released)


def test_delegate_hands_the_lease_to_comfy():
    with TestClient(app) as c:
        runner = c.app.state.runner
        seen = {}

        class Comfy:
            reduce = None

            async def run(self, req, jdir, inputs, on_event, cancel_check, gpu_headers=None):
                seen["headers"] = gpu_headers
                return {}

        runner.comfy = Comfy()
        runner.lease = Lease(id="gl_job", state="granted")
        asyncio.run(runner.delegate(None, None, {}, None, lambda: False))
        assert seen["headers"] == {"X-GAIFA-GPU-Lease": "gl_job"}
        runner.lease = None


def test_comfy_engine_sends_the_lease_header(tmp_path):
    hub = ComfyHub()
    seen = []
    real = hub.__call__

    def spy(request):
        if request.url.path.endswith("/v1/run"):
            seen.append(request.headers.get("x-gaifa-gpu-lease"))
        return real(request)

    engine = ComfyEngine("http://hub", httpx.MockTransport(spy), poll_s=0)
    orig = engine.run

    async def with_lease(*a, **kw):
        return await orig(*a, gpu_headers={"X-GAIFA-GPU-Lease": "gl_job"}, **kw)

    engine.run = with_lease
    comfy_run(engine, {"engine": "trellis2"}, tmp_path)
    assert seen == ["gl_job"]
