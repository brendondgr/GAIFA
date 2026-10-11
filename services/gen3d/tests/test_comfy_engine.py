"""Delegated engines (plan 17.6): gen3d runs TRELLIS.2 and SAM 3D Body as comfy packs through a (fake) hub."""

import asyncio
import json

import httpx
import pytest

from gen3d.comfy_engine import ComfyEngine, ComfyError, plan
from gen3d.glb import boxes_glb, count_faces
from gen3d.options import parse_request

BIG = boxes_glb([{"name": f"b{i}", "center": (i, 0, 0), "size": (1, 1, 1)} for i in range(5)])   # 60 faces
SMALL = boxes_glb([{"name": "b", "center": (0, 0, 0), "size": (1, 1, 1)}])                       # 12 faces


class Hub:
    def __init__(self, final="done", outputs=("comfy/d/raw.glb", "comfy/d/small.glb"), error=None):
        self.calls, self.final, self.outputs, self.error, self.polls = [], final, list(outputs), error, 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        p, m = request.url.path, request.method
        self.calls.append((m, p, request.content if m == "POST" and p.endswith("/run") else None,
                           request.headers.get("x-aihub-make-room")))
        if p == "/api/s/comfy/v1/uploads":
            return httpx.Response(200, json={"value": "upload:pic.png"})
        if p == "/api/s/comfy/v1/run":
            return httpx.Response(202, json={"id": "r-1", "state": "queued", "progress": 0})
        if p == "/api/s/comfy/v1/jobs/r-1":
            self.polls += 1
            if self.polls < 3:
                return httpx.Response(200, json={"id": "r-1", "state": "running", "progress": 0.4 * self.polls})
            return httpx.Response(200, json={"id": "r-1", "state": self.final, "progress": 1.0, "error": self.error,
                                             "outputs": [{"path": o, "kind": "model3d"} for o in self.outputs], "peak_gb": 21.9})
        if p.startswith("/api/s/comfy/v1/files/"):
            return httpx.Response(200, content=SMALL if p.endswith("small.glb") else BIG)
        if p == "/api/outputs":
            q = request.url.params["q"]
            return httpx.Response(200, json={"items": [{"id": f"o-{q}", "path": f"outputs/comfy/d/{q}"}]})
        if m == "DELETE" and p.startswith("/api/outputs/"):
            return httpx.Response(204)
        if p.endswith("/cancel"):
            return httpx.Response(200, json={"id": "r-1", "state": "cancelled"})
        return httpx.Response(404, json={"detail": f"no route {p}"})


def run(engine, raw, tmp_path, cancel_check=lambda: False):
    (tmp_path / "input_rgba.png").write_bytes(b"png")
    (tmp_path / "input.png").write_bytes(b"png")
    events = []
    req = parse_request({"image": "output:o", **raw})
    inputs = {"image": str(tmp_path / "input_rgba.png"), "image_raw": str(tmp_path / "input.png")}
    async def go():
        out = await engine.run(req, tmp_path, inputs, events.append, cancel_check)
        await asyncio.gather(*engine._bg)                         # the trash step runs in the background
        return out
    return asyncio.run(go()), events


def test_plan_picks_the_pack():
    assert plan(parse_request({"engine": "trellis2", "image": "output:o"}))[0] == "trellis2-shape"
    assert plan(parse_request({"engine": "trellis2", "image": "output:o", "preset": "draft"}))[0] == "trellis2-draft"
    pack, key, values, _ = plan(parse_request({"engine": "trellis2", "image": "output:o", "trellis2": {"target_faces": 50000}}))
    assert pack == "trellis2-lowpoly" and values["target_faces"] == 50000 and values["refine_steps"] == 6
    pack, key, values, _ = plan(parse_request({"engine": "sam3d_body", "image": "output:o", "preset": "base"}))
    assert (pack, key, values["hand_refinement"]) == ("sam3d-body", "image_raw", True)


def test_a_lowpoly_run_keeps_both_meshes(tmp_path):
    hub = Hub()
    out, events = run(ComfyEngine("http://hub", httpx.MockTransport(hub), poll_s=0), {"engine": "trellis2", "trellis2": {"target_faces": 50000}}, tmp_path)
    assert out["mesh"] == "mesh.glb" and out["raw"] == "mesh_raw.glb" and out["comfy"]["workflow"] == "trellis2-lowpoly"
    assert count_faces(tmp_path / "mesh.glb") == 12 and count_faces(tmp_path / "mesh_raw.glb") == 60 and out["faces"] == 12
    assert out["peak_gpu_gb"] == 21.9 and not list(tmp_path.glob(".comfy-*"))
    run_call = next(c for c in hub.calls if c[1].endswith("/v1/run"))
    body = json.loads(run_call[2])
    assert body["workflow"] == "trellis2-lowpoly" and body["inputs"]["image"] == "upload:pic.png" and run_call[3] == "1"
    assert [e["step"] for e in events if e["event"] == "progress"] == [40, 80, 100]
    assert events[0]["sub"] == "trellis2.comfy" and events[-1]["event"] == "sub_done"
    assert sum(1 for c in hub.calls if c[0] == "DELETE") == 2          # comfy's copies go to the trash


def test_a_failed_run_is_the_stage_error(tmp_path):
    hub = Hub(final="failed", error="CUDA out of memory")
    with pytest.raises(ComfyError, match="out of memory"):
        run(ComfyEngine("http://hub", httpx.MockTransport(hub), poll_s=0), {"engine": "trellis2"}, tmp_path)


def test_cancel_reaches_comfy(tmp_path):
    hub = Hub()
    with pytest.raises(ComfyError, match="canceled"):
        run(ComfyEngine("http://hub", httpx.MockTransport(hub), poll_s=0), {"engine": "sam3d_body"}, tmp_path,
            cancel_check=lambda: hub.polls >= 1)
    assert any(c[1] == "/api/s/comfy/v1/queue/r-1/cancel" for c in hub.calls)


def test_the_draft_reduces_in_gen3d(tmp_path):
    seen = {}

    async def reduce(mesh, target, jdir, on_event):
        seen.update(mesh=mesh.name, target=target)
        (jdir / "mesh.glb").write_bytes(SMALL)
        return {"mesh": "mesh.glb", "raw_faces": 60}

    engine = ComfyEngine("http://hub", httpx.MockTransport(Hub(outputs=["comfy/d/raw.glb"])), poll_s=0, reduce=reduce)
    out, _ = run(engine, {"engine": "trellis2", "preset": "draft", "trellis2": {"target_faces": 20000}}, tmp_path)
    assert seen == {"mesh": "mesh_raw.glb", "target": 20000} and out["raw"] == "mesh_raw.glb" and out["faces"] == 12


def test_hub_errors_are_readable(tmp_path):
    def handler(request):
        if request.url.path.endswith("/uploads"):
            return httpx.Response(200, json={"value": "upload:x"})
        return httpx.Response(409, json={"detail": "needs room: unload lcpp first"})
    with pytest.raises(ComfyError, match="needs room"):
        run(ComfyEngine("http://hub", httpx.MockTransport(handler), poll_s=0), {"engine": "trellis2"}, tmp_path)
