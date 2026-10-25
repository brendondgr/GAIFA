"""The delegated image engines (plan 17.6): TRELLIS.2 and SAM 3D Body run as workflow packs in the comfy
mod, through the hub. gen3d still owns the job: it uploads the picture, runs the pack with
`X-GAIFA-Make-Room: 1` (the job already asked for room) and the job's GPU lease, turns comfy's 0–1 progress into the stage's
steps, downloads the mesh into the job folder and moves comfy's copy to the hub's trash, so the
Outputs page shows the job once.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

import httpx

from .glb import count_faces

log = logging.getLogger("gen3d.comfy")
COMFY = "/api/s/comfy"
MAKE_ROOM = {"X-GAIFA-Make-Room": "1"}


class ComfyError(RuntimeError):
    pass


def plan(req) -> tuple[str, str, dict, str]:
    """(pack, picture key in inputs, pack inputs, substage) for a delegated request."""
    if req.engine == "trellis2":
        o = req.trellis2
        common = {"seed": o.seed, "structure_steps": o.structure_steps, "shape_steps": o.shape_steps, "guidance": o.guidance}
        if o.resolution == 512:
            return "trellis2-draft", "image", common, "trellis2.comfy"
        full = {**common, "refine_steps": o.refine_steps, "resolution": o.resolution}
        if o.target_faces:
            return ("trellis2-lowpoly", "image",
                    {**full, "target_faces": o.target_faces, "remesh_resolution": o.remesh_resolution}, "trellis2.comfy")
        return "trellis2-shape", "image", full, "trellis2.comfy"
    if req.engine == "sam3d_body":
        o = req.sam3d_body
        return "sam3d-body", "image_raw", {"hand_refinement": o.hand_refinement, "fov": o.fov}, "sam3d_body.comfy"
    raise ValueError(f"{req.engine} isn't a delegated engine")


class ComfyEngine:
    def __init__(self, hub_url: str, transport: httpx.AsyncBaseTransport | None = None, poll_s: float = 2.0,
                 reduce=None):
        self.hub = hub_url.rstrip("/")
        self.transport, self.poll_s = transport, poll_s
        self.reduce = reduce                 # async (mesh, target, job_dir) -> dict: the draft's fallback reduction
        self.current: str | None = None      # the comfy job running for gen3d
        self._bg: set[asyncio.Task] = set()

    def _client(self, timeout: float = 60) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self.hub, timeout=timeout, transport=self.transport)

    async def run(self, req, jdir: Path, inputs: dict, on_event, cancel_check, gpu_headers: dict | None = None) -> dict:
        """`gpu_headers`: the job's GPU lease (`X-GAIFA-GPU-Lease`), so comfy runs under it (plan 31.3)."""
        pack, key, values, sub = plan(req)
        picture = inputs.get(key) or inputs.get("image")
        async with self._client() as c:
            with open(picture, "rb") as f:
                r = await c.post(f"{COMFY}/v1/uploads", files={"file": (Path(picture).name, f, "image/png")})
            _ok(r, "upload the picture to comfy")
            values["image"] = r.json()["value"]
            on_event({"event": "sub", "sub": sub, "total": 100, "note": f"comfy: {pack}"})
            r = await c.post(f"{COMFY}/v1/run", json={"workflow": pack, "inputs": values},
                             headers={**MAKE_ROOM, **(gpu_headers or {})}, timeout=120)
            _ok(r, f"run {pack}")
            job = r.json()
            self.current = job["id"]
            t0, last = asyncio.get_running_loop().time(), -1
            try:
                while job.get("state") in ("queued", "running", None):
                    if cancel_check():
                        await c.post(f"{COMFY}/v1/queue/{job['id']}/cancel")
                        raise ComfyError("canceled")
                    r = await c.get(f"{COMFY}/v1/jobs/{job['id']}", params={"wait": self.poll_s}, timeout=self.poll_s + 30)
                    _ok(r, "follow the comfy run")
                    job = r.json()
                    step = int(round(100 * float(job.get("progress") or 0)))
                    if step != last:
                        on_event({"event": "progress", "step": step, "total": 100})
                        last = step
            finally:
                self.current = None
            if job.get("state") != "done":
                raise ComfyError(f"{pack}: {job.get('error') or job.get('state')}")
            outs = [o for o in job.get("outputs") or [] if str(o.get("path", "")).endswith(".glb")]
            if not outs:
                raise ComfyError(f"{pack} finished without a mesh")
            files = []
            for o in outs:
                dest = jdir / f".comfy-{len(files)}.glb"
                async with c.stream("GET", f"{COMFY}/v1/files/{o['path']}", timeout=600) as resp:
                    if resp.status_code >= 400:
                        await resp.aread()
                        _ok(resp, "download the mesh")
                    with open(dest, "wb") as fh:
                        async for chunk in resp.aiter_bytes(1 << 20):
                            fh.write(chunk)
                files.append(dest)
            on_event({"event": "sub_done", "sub": sub, "seconds": asyncio.get_running_loop().time() - t0})
        task = asyncio.create_task(self._trash([o["path"] for o in outs]))
        self._bg.add(task)
        task.add_done_callback(self._bg.discard)
        files.sort(key=lambda p: p.stat().st_size)               # the reduced mesh is the small one
        out = {"mesh": "mesh.glb", "engine": req.engine, "comfy": {"workflow": pack, "run": job["id"]}}
        if len(files) > 1:
            files[-1].replace(jdir / "mesh_raw.glb")
            out["raw"], out["raw_faces"] = "mesh_raw.glb", count_faces(jdir / "mesh_raw.glb")
        files[0].replace(jdir / "mesh.glb")
        for extra in files[1:-1]:
            extra.unlink(missing_ok=True)
        target = getattr(getattr(req, req.engine), "target_faces", 0)
        if target and len(files) == 1 and self.reduce is not None:     # the draft: no remesh pack, reduce here
            (jdir / "mesh.glb").replace(jdir / "mesh_raw.glb")
            out.update(await self.reduce(jdir / "mesh_raw.glb", target, jdir, on_event))
            out["raw"] = "mesh_raw.glb"
        out["faces"] = count_faces(jdir / "mesh.glb")
        if job.get("peak_gb"):
            out["peak_gpu_gb"] = job["peak_gb"]
        return out

    async def _trash(self, paths: list[str], tries: int = 10, wait_s: float = 2.0) -> None:
        """comfy's copies of the meshes go to the hub's trash (best effort): the job folder has them. The
        hub indexes a new output a moment after it lands, so look again for a while."""
        left = list(paths)
        async with self._client(30) as c:
            for attempt in range(tries):
                for p in list(left):
                    try:
                        r = await c.get("/api/outputs", params={"service": "comfy", "q": Path(p).name, "limit": 5})
                        for item in (r.json().get("items") or []) if r.status_code == 200 else []:
                            if item.get("path") == f"outputs/{p}":
                                await c.delete(f"/api/outputs/{item['id']}")
                                left.remove(p)
                    except (httpx.HTTPError, ValueError) as exc:
                        log.info("couldn't trash comfy's copy of %s: %s", p, exc)
                if not left:
                    return
                await asyncio.sleep(wait_s)
        log.info("comfy's copies not found in the outputs index: %s", ", ".join(left))

    async def cancel(self) -> None:
        if self.current:
            try:
                async with self._client(10) as c:
                    await c.post(f"{COMFY}/v1/queue/{self.current}/cancel")
            except httpx.HTTPError:
                pass


def _ok(r: httpx.Response, what: str) -> None:
    if r.status_code >= 400:
        try:
            detail = r.json().get("detail")
        except ValueError:
            detail = r.text[:300]
        raise ComfyError(f"couldn't {what}: {detail or r.status_code}")


def from_env() -> ComfyEngine | None:
    url = os.environ.get("GAIFA_URL")
    return ComfyEngine(url) if url else None
