"""The job runner: one job on the GPU at a time, FIFO, with progress, ETA, cancel and idle unload.

Stages run in order; each reads its input from this job's earlier output, the parent job's output
(`parent_id`), or an uploaded mesh. A stage that finished before a server restart is not re-run.

The GPU slot (plan 31.3): a job takes AIHub's slot (`gpu_slot.py`) before its first stage and holds it
across all of them, the Blender preview included; memory is asked for after it. While it waits, the
job stays `queued` with `stage: "waiting_gpu"` (`ahead`, `eta_s`). The lease goes to comfy in
`X-AIHub-GPU-Lease` when TRELLIS.2 or SAM 3D Body run there, so comfy runs under it.
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

from .live import live_of
from .config import settings
from .engines import ENGINES
from .eta import Estimator, substages
from .events import Broadcaster
from .gpu_slot import GpuSlot
from .options import JobRequest, parse_request
from .store import TERMINAL, Store

log = logging.getLogger("gen3d.queue")
PUBLISH_EVERY_S = 0.5


class StageError(RuntimeError):
    pass


class Canceled(Exception):
    pass


class Runner:
    def __init__(self, store: Store, worker, previewer, events: Broadcaster, eta_scale: float = 1.0, comfy=None,
                 gpu: GpuSlot | None = None):
        self.store = store
        self.gpu = gpu or GpuSlot(service="gen3d")     # AIHUB_URL from the environment; none: runs at once
        self.lease = None                               # the running job's GPU lease
        self.gpu_wait: dict[str, dict] = {}             # job id → {ahead, eta_s} while it waits for the slot
        self._cancel_waiting: set[str] = set()
        self.worker = worker                # a WorkerPool: one container per engine family, one at a time
        self.comfy = comfy                  # the delegated engines' runner (comfy_engine.ComfyEngine), or None
        if comfy is not None:
            comfy.reduce = self._reduce
        self.previewer = previewer          # async (job_dir, glb, png) -> None
        self.events = events
        self.eta = Estimator(store, scale=eta_scale)
        self.current: str | None = None
        self._wake = asyncio.Event()
        self._cancel: set[str] = set()
        self._task: asyncio.Task | None = None
        self._last_pub = 0.0
        self.last_activity = time.monotonic()

    # ---- lifecycle ------------------------------------------------------------------------------

    def start(self) -> None:
        for jid in self.store.requeue_interrupted():
            log.info("requeued %s (interrupted by a restart)", jid)
        self._task = asyncio.create_task(self._loop())
        self._wake.set()

    async def stop(self) -> None:
        interrupted = self.current is not None  # that job goes back to the queue at next start
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        await self.worker.stop(reason="server shutting down", graceful=not interrupted)

    def kick(self) -> None:
        self._wake.set()

    async def _loop(self) -> None:
        while True:
            queued = self.store.queued()
            if not queued:
                self._wake.clear()
                try:
                    await asyncio.wait_for(self._wake.wait(), 15)
                except asyncio.TimeoutError:
                    await self._maybe_idle_unload()
                continue
            job = queued[0]
            try:
                await self._run(job["id"])
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("job %s crashed the runner", job["id"])
                self.store.update_job(job["id"], status="failed", error="internal error (see gen3d logs)",
                                      finished=time.time())
                self.store.write_output_json(job["id"])
                self.publish_job(job["id"])
            self.last_activity = time.monotonic()

    async def _maybe_idle_unload(self) -> None:
        if settings.idle_unload_s > 0 and self.worker.up and not self.current and \
                time.monotonic() - self.last_activity > settings.idle_unload_s:
            await self.worker.stop(reason=f"idle {settings.idle_unload_s:.0f}s")
            self.events.publish("worker", self.worker.status())

    # ---- one job --------------------------------------------------------------------------------

    async def _run(self, jid: str) -> None:
        job = self.store.get_job(jid)
        req = JobRequest.model_validate(job["request"])
        self.current = jid

        def on_wait(lease) -> None:
            self.gpu_wait[jid] = {"ahead": lease.ahead, "eta_s": lease.eta_s}
            self.publish_job(jid)

        est = (self.schedule().get(jid) or {}).get("own_s")
        try:
            async with self.gpu.slot(f"3D model: {job.get('title') or jid}"[:120], est_s=est, on_wait=on_wait) as lease:
                self.gpu_wait.pop(jid, None)
                if self.store.get_job(jid)["status"] in TERMINAL:      # cancelled as the slot came
                    return
                self.lease = lease
                await self._run_held(jid, req)
        except asyncio.CancelledError:
            if jid not in self._cancel_waiting:
                raise
            asyncio.current_task().uncancel()           # cancel() stopped the wait for the slot, not the runner
        finally:
            self._cancel_waiting.discard(jid)
            self.gpu_wait.pop(jid, None)
            self.lease = None
            self.current = None

    async def _run_held(self, jid: str, req: JobRequest) -> None:
        job = self.store.get_job(jid)
        self.store.update_job(jid, status="running", started=job.get("started") or time.time(), error=None)
        self.publish_job(jid)
        try:
            for stage in list(job["stages"]):
                job = self.store.get_job(jid)
                if job["stages"][stage].get("state") == "done":
                    continue
                if jid in self._cancel:
                    raise Canceled()
                await self._run_stage(jid, stage, req)
            self.store.update_job(jid, status="done", finished=time.time())
        except Canceled:
            self._mark_rest(jid, "canceled")
            self.store.update_job(jid, status="canceled", finished=time.time(), error=None)
        except StageError as exc:
            self._mark_rest(jid, "skipped")
            self.store.update_job(jid, status="failed", finished=time.time(), error=str(exc))
        finally:
            self._cancel.discard(jid)
            self.current = None
            self.store.write_output_json(jid)
            self.publish_job(jid)
            self.events.publish("worker", self.worker.status())

    def _mark_rest(self, jid: str, state: str) -> None:
        job = self.store.get_job(jid)
        stages = job["stages"]
        for s, v in stages.items():
            if v.get("state") == "running":
                v["state"] = "canceled" if state == "canceled" else "failed"
                v["finished"] = time.time()
            elif v.get("state") == "pending":
                v["state"] = state
        self.store.update_job(jid, stages=stages)

    def _inputs(self, jid: str, stage: str) -> dict:
        """Where this stage reads from: this job's output first, then the parent's, then an upload."""
        job = self.store.get_job(jid)
        jdir = self.store.job_dir(jid)
        chain = [(job, jdir)]
        pid = job.get("parent_id")
        while pid:  # follow the whole chain (a rig of a split of a shape)
            parent = self.store.get_job(pid)
            if not parent:
                break
            chain.append((parent, self.store.job_dir(pid)))
            pid = parent.get("parent_id")

        def find(key: str, sub: str) -> str | None:
            for j, d in chain:
                val = (j["result"].get(key) or {}).get(sub)
                if val and (d / val).exists():
                    return str(d / val)
            return None

        mesh = find("shape", "mesh")
        if not mesh:
            for j, d in chain:
                if j.get("input_mesh") and (d / j["input_mesh"]).exists():
                    mesh = str(d / j["input_mesh"]); break
        parts = find("parts", "dir")
        newest = find("rig", "glb") or find("parts", "scene") or mesh
        image = next((str(d / "input_rgba.png") for _, d in chain if (d / "input_rgba.png").exists()), None)
        return {"mesh": mesh, "parts_dir": parts, "newest": newest, "image": image,
                "image_raw": image and str(Path(image).with_name("input.png"))}

    async def _run_stage(self, jid: str, stage: str, req: JobRequest) -> None:
        jdir = self.store.job_dir(jid)
        inputs = self._inputs(jid, stage)
        if stage == "parts" and not inputs["mesh"]:
            raise StageError("no mesh to split: add the shape stage, continue from a job with a mesh, or upload one")
        if stage == "rig" and not inputs["parts_dir"]:
            raise StageError("no parts to rig: add the parts stage or continue from a job that has parts")
        if stage == "preview" and not inputs["newest"]:
            raise StageError("nothing to preview yet")
        engine = ENGINES[req.engine]
        if stage == "shape" and engine.input == "image" and not inputs["image"]:
            raise StageError("no picture for the image engine: give `image`, or retry from the job that had one")

        started = time.time()
        self._set_stage(jid, stage, state="running", started=started, sub=None, step=None, total=None)
        features = {sub: feat for sub, feat, _, _ in
                    [x for st in ("shape", "parts", "rig", "preview") for x in substages(req, st, set())]}

        def on_event(ev: dict) -> None:
            kind = ev.get("event")
            if kind == "sub":
                self._set_stage(jid, stage, sub=ev["sub"], step=0, total=ev.get("total"),
                                sub_started=time.time(), note=ev.get("note"), publish=True)
            elif kind == "progress":
                self._set_stage(jid, stage, step=ev.get("step"), total=ev.get("total"))
            elif kind == "sub_done":
                if ev.get("sub") in features or ev.get("sub", "").startswith("load."):
                    self.eta.record(ev["sub"], features.get(ev["sub"], {}), float(ev["seconds"]))
            elif kind == "log":
                log.info("[worker] %s", ev.get("message"))

        try:
            if stage == "preview":
                png = jdir / "preview.png"
                on_event({"event": "sub", "sub": "preview"})
                t0 = time.time()
                await self.previewer(jdir, Path(inputs["newest"]), png)
                on_event({"event": "sub_done", "sub": "preview", "seconds": time.time() - t0})
                result = {"png": "preview.png"} if png.exists() else {"skipped": "Blender not available"}
            elif stage == "shape" and not engine.local:
                await self.worker.stop(reason=f"{engine.label} runs in the comfy mod")     # its memory, back first
                result = await self.delegate(req, jdir, inputs, on_event, cancel_check=lambda: jid in self._cancel)
            else:
                family = engine.worker if stage == "shape" else "cube"
                if stage == "shape" and engine.memory_gb:
                    from .hubclient import acquire
                    await acquire(engine.memory_gb, f"{engine.label}: {req.title or jid}")
                task = {"stage": stage, "family": family, "engine": req.engine, "job_dir": str(jdir),
                        "request": req.model_dump(), "inputs": inputs}
                result = await self.worker.run(task, on_event, cancel_check=lambda: jid in self._cancel)
        except Canceled:
            raise
        except Exception as exc:
            if jid in self._cancel:
                raise Canceled() from exc
            self._set_stage(jid, stage, state="failed", finished=time.time(), error=str(exc))
            raise StageError(f"{stage} failed: {exc}") from exc

        job = self.store.get_job(jid)
        res = job["result"]
        res[stage] = result
        self.store.update_job(jid, result=res)
        self._set_stage(jid, stage, state="done", finished=time.time(), seconds=round(time.time() - started, 1),
                        sub=None, step=None, total=None, publish=True)

    async def _reduce(self, mesh: Path, target: int, jdir: Path, on_event) -> dict:
        """Reduce a delegated engine's mesh in the img3d worker (fast-simplification), for TRELLIS.2's draft."""
        task = {"stage": "reduce", "family": "img3d", "mesh": str(mesh), "target": target, "job_dir": str(jdir)}
        return await self.worker.run(task, on_event)

    async def delegate(self, req: JobRequest, jdir: Path, inputs: dict, on_event, cancel_check) -> dict:
        """TRELLIS.2 and SAM 3D Body: a run of their comfy pack through the hub (gen3d/comfy_engine.py)."""
        if self.comfy is None:
            raise StageError(f"{ENGINES[req.engine].label} runs in the comfy mod, which needs AIHub (AIHUB_URL)")
        # comfy runs under this job's GPU lease instead of queueing behind it
        return await self.comfy.run(req, jdir, inputs, on_event, cancel_check,
                                    gpu_headers=self.lease.headers if self.lease else {})

    def _set_stage(self, jid: str, stage: str, publish: bool = False, **fields) -> None:
        job = self.store.get_job(jid)
        st = job["stages"]
        st.setdefault(stage, {}).update({k: v for k, v in fields.items()})
        self.store.update_job(jid, stages=st)
        now = time.monotonic()
        if publish or "state" in fields or now - self._last_pub > PUBLISH_EVERY_S:
            self._last_pub = now
            self.publish_job(jid)

    # ---- cancel / views -------------------------------------------------------------------------

    async def cancel(self, jid: str) -> dict | None:
        job = self.store.get_job(jid)
        if not job or job["status"] in TERMINAL:
            return job
        if job["status"] == "queued":
            if jid == self.current and jid in self.gpu_wait and self._task:   # waiting for the GPU slot: stop waiting
                self._cancel_waiting.add(jid)
                self._task.cancel()
            self._mark_rest(jid, "canceled")
            self.store.update_job(jid, status="canceled", finished=time.time())
            self.store.write_output_json(jid)
            self.publish_job(jid)
            return self.store.get_job(jid)
        self._cancel.add(jid)
        await self.worker.cancel()  # stops the worker process: the only way to interrupt a GPU call
        if self.comfy is not None:
            await self.comfy.cancel()  # a delegated stage: cancel its comfy run
        for _ in range(100):  # the runner notices within a moment; answer with the final state
            job = self.store.get_job(jid)
            if job["status"] in TERMINAL:
                break
            await asyncio.sleep(0.1)
        return job

    def schedule(self) -> dict[str, dict]:
        """ETA for every active job: the running one from live progress, queued ones after it."""
        now = time.time()
        out: dict[str, dict] = {}
        offset = 0.0
        loaded = set(self.worker.loaded)
        up = self.worker.up
        active = []
        if self.current:
            cur = self.store.get_job(self.current)
            if cur and cur["status"] == "running":
                active.append(cur)
        active += self.store.queued()
        for pos, job in enumerate(active):
            try:
                req = JobRequest.model_validate(job["request"])
            except Exception:
                continue
            rem = self.eta.remaining(job, req, loaded, up, now)
            out[job["id"]] = {"queue_position": pos, "starts_in_s": round(offset, 1),
                              "eta_s": round(offset + rem["eta_s"], 1), "own_s": rem["eta_s"],
                              "by_stage": rem["by_stage"], "done_at": now + offset + rem["eta_s"]}
            offset += rem["eta_s"]
            loaded |= {("shape" if req.engine == "cube3d" else req.engine) if s == "shape" else s
                       for s in job["stages"] if s in ("shape", "parts")}
            up = True
        return out

    def estimate(self, raw: dict) -> dict:
        req = parse_request(raw)
        sched = self.schedule()
        wait = max((v["eta_s"] for v in sched.values()), default=0.0)
        loaded = set(self.worker.loaded) if not sched else {"shape", "parts"} & set(self.worker.loaded)
        plan = self.eta.plan(req, req.stages, loaded, self.worker.up or bool(sched))
        own = sum(p["seconds"] for p in plan)
        return {"plan": plan, "own_s": round(own, 1), "wait_s": round(wait, 1),
                "eta_s": round(wait + own, 1), "done_at": time.time() + wait + own}

    def public(self, job: dict, sched: dict | None = None) -> dict:
        sched = self.schedule() if sched is None else sched
        jdir = self.store.job_dir(job["id"])
        files = sorted(str(p.relative_to(jdir)) for p in jdir.rglob("*") if p.is_file()) if jdir.exists() else []
        out = {k: v for k, v in job.items()}
        out["files"] = files
        out["eta"] = sched.get(job["id"])
        lv = live_of(job, sched.get(job["id"]), jdir)          # plan 45.3: stages, time left, the cut-out, the views
        if lv:
            out["live"] = lv
        w = self.gpu_wait.get(job["id"]) if job.get("status") == "queued" else None
        if w is not None:                                   # plan 31.3: what runs on the GPU before it
            out.update(stage="waiting_gpu", ahead=w["ahead"], eta_s=w["eta_s"])
        return out

    def publish_job(self, jid: str) -> None:
        """Send the job's current state to every /v1/events listener."""
        job = self.store.get_job(jid)
        if job:
            self.events.publish("job", self.public(job))

    def health(self) -> dict:
        sched = self.schedule()
        return {"running": 1 if self.current else 0, "queued": len(self.store.queued()),
                "current": self.current,
                "eta_s": round(max((v["eta_s"] for v in sched.values()), default=0.0), 1)}
