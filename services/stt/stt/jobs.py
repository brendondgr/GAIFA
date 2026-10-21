"""File transcription jobs, one at a time: input → canonical audio → pause-cut chunks → outputs.

An upload waits in ``runtime/tmp`` until its job ends (done, failed or cancelled, queued or not);
at most ``MAX_QUEUED_UPLOADS`` wait at once, and files left by a crash are swept at startup. A
running job holds a lease on its model (``Engine.acquire``); when a live stream holds another model,
the job waits in stage ``waiting`` until it ends. On the GPU, a job first takes AIHub's GPU slot (plan
31.3): while another mod's work holds it, the job is ``queued`` in stage ``waiting_gpu``."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import shutil
import time
import uuid
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from typing import Any

from . import catalog, transcripts
from .audio.decode import DecodeError, decode
from .audio.formats import SAMPLE_RATE
from .batch.batch import transcribe_samples
from .config import MOD_DIR, VadConfig
from .engine import Engine, ModelBusy
from .gpu import Gpu, GpuCancelled
from .hub import Hub, HubError
from .vad import build_detector

logger = logging.getLogger(__name__)

TMP = MOD_DIR / "runtime" / "tmp"
KEEP = 50                    # finished jobs remembered
MAX_QUEUED_UPLOADS = 8       # uploads received or waiting in runtime/tmp at once (4 GB each at most)
STALE_S = 3600               # files in runtime/tmp older than this are swept at startup
WAIT_POLL_S = 1.0            # how often a job waiting for another model looks again


@dataclass
class Job:
    id: str
    label: str
    model: str
    language: str | None = None
    prompt: str | None = None
    timestamps: str = "segments"
    save: bool = True
    source: dict[str, Any] = field(default_factory=dict)   # {"output_id"} or {"upload": name}
    upload: Path | None = None
    state: str = "queued"     # queued | running | done | failed | cancelled
    stage: str = "queued"     # fetching | decoding | waiting_gpu | waiting | loading | transcribing | saving
    progress: float = 0.0
    created: float = field(default_factory=time.time)
    started: float | None = None
    finished: float | None = None
    duration: float | None = None
    result: dict[str, Any] | None = None
    transcript: str | None = None        # the [mm:ss] paragraphs, for the agent's tool result
    error: str | None = None
    cancel: bool = False
    ahead: list[dict[str, Any]] = field(default_factory=list)   # waiting_gpu: what runs before it
    eta_s: float | None = None

    def view(self) -> dict[str, Any]:
        out = {"id": self.id, "label": self.label, "state": self.state, "stage": self.stage,
               "progress": round(self.progress, 3), "model": self.model, "language": self.language,
               "created": self.created, "started": self.started, "finished": self.finished,
               "duration": self.duration, "source": self.source, "error": self.error}
        if self.stage == "waiting_gpu":
            out["ahead"], out["eta_s"] = self.ahead, self.eta_s
        if self.result is not None:
            out["result"] = self.result
            out["transcript"] = self.transcript
            if "output" in self.result:
                out["files"] = self.result["files"]
        if self.started and self.finished and self.duration:
            out["rtf"] = round((self.finished - self.started) / self.duration, 4)
        return out


class Jobs:
    def __init__(self, engine: Engine, hub: Hub, outputs: Path, mod: str = "stt", gpu: Gpu | None = None) -> None:
        self.engine, self.hub, self.outputs, self.mod, self.gpu = engine, hub, outputs, mod, gpu
        self.tmp = TMP
        self.receiving = 0           # uploads being written to runtime/tmp right now
        self.jobs: dict[str, Job] = {}
        self._queue: asyncio.Queue[Job] = asyncio.Queue()
        self.done_today = 0
        self.audio_today = 0.0

    def submit(self, *, label: str, model: str | None = None, preset: str | None = None, **kw: Any) -> Job:
        name = catalog.pick(model, preset)
        job = Job(id=f"j_{uuid.uuid4().hex[:10]}", label=label[:80] or "audio", model=name, **kw)
        self.jobs[job.id] = job
        self._queue.put_nowait(job)
        self._trim()
        return job

    def uploads_waiting(self) -> int:
        """Uploads being received or queued: each holds a file in runtime/tmp."""
        return self.receiving + sum(1 for j in self.jobs.values() if j.upload is not None and j.state == "queued")

    def sweep(self, max_age: float = STALE_S) -> int:
        """Delete files and job folders in runtime/tmp older than ``max_age`` (left by a crash)."""
        if not self.tmp.is_dir():
            return 0
        cutoff, swept = time.time() - max_age, 0
        for entry in self.tmp.iterdir():
            try:
                if entry.lstat().st_mtime >= cutoff:
                    continue
                if entry.is_dir() and not entry.is_symlink():
                    shutil.rmtree(entry, ignore_errors=True)
                else:
                    entry.unlink(missing_ok=True)
                swept += 1
            except OSError:
                continue
        if swept:
            logger.info("Swept %d stale files from %s", swept, self.tmp)
        return swept

    def get(self, jid: str) -> Job | None:
        return self.jobs.get(jid)

    def list(self) -> list[Job]:
        return sorted(self.jobs.values(), key=lambda j: j.created, reverse=True)

    def cancel(self, jid: str) -> Job | None:
        job = self.jobs.get(jid)
        if job and job.state in ("queued", "running"):
            job.cancel = True
            if job.state == "queued":
                self._finish(job, "cancelled")
                self._drop_upload(job)
        return job

    @staticmethod
    def _drop_upload(job: Job) -> None:
        if job.upload is not None:
            job.upload.unlink(missing_ok=True)

    async def run(self) -> None:
        while True:
            job = await self._queue.get()
            if job.state != "queued":
                self._drop_upload(job)
                continue
            try:
                await self._run(job)
            except Exception as exc:  # noqa: BLE001 - one bad file never stops the queue
                logger.exception("Job %s failed", job.id)
                job.error = str(exc) or type(exc).__name__
                self._finish(job, "failed")
            finally:
                self._drop_upload(job)

    async def _run(self, job: Job) -> None:
        job.state, job.started = "running", time.time()
        work = self.tmp / job.id
        try:
            path = job.upload
            if path is None:
                job.stage = "fetching"
                try:
                    path, record = await self.hub.fetch_output(job.source["output_id"], work, "input")
                except HubError as exc:
                    raise ValueError(str(exc)) from exc
                if job.label in ("", "audio"):
                    job.label = re.sub(r"\.(wav|mp3|flac|ogg|opus|m4a|aac|mp4|webm|mov|mkv)$", "",
                                       str(record.get("title") or job.label), flags=re.I)[:80]
            job.stage = "decoding"
            try:
                samples = await asyncio.to_thread(decode, path)
            except DecodeError as exc:
                raise ValueError(str(exc)) from exc
        finally:
            shutil.rmtree(work, ignore_errors=True)
        job.duration = samples.size / SAMPLE_RATE
        if job.cancel:
            return self._finish(job, "cancelled")
        async with contextlib.AsyncExitStack() as stack:
            if not await self._take_gpu(job, stack):
                return self._finish(job, "cancelled")
            await self._transcribe(job, samples)

    async def _take_gpu(self, job: Job, stack: contextlib.AsyncExitStack) -> bool:
        """The GPU slot, when the model runs on the GPU; False when the job was cancelled while it waited."""
        if self.gpu is None or not self.gpu.enabled or self.engine.fell_back or not await self.engine.gpu():
            return True

        def waiting(lease) -> None:
            job.state, job.stage, job.ahead, job.eta_s = "queued", "waiting_gpu", lease.ahead, lease.eta_s

        rtf = self.engine.inference_seconds / self.engine.audio_seconds if self.engine.audio_seconds else None
        est = round((job.duration or 0) * rtf + 5, 1) if rtf else None
        try:
            lease = await self.gpu.enter(stack, f"Transcribe: {job.label}", cls="job", est_s=est,
                                         stop=lambda: job.cancel, on_wait=waiting)
        except GpuCancelled:
            job.cancel, job.error = True, "cancelled in the GPU queue"
            return False
        if lease is None or job.cancel:
            return False
        job.state, job.ahead, job.eta_s = "running", [], None
        return True

    async def _transcribe(self, job: Job, samples) -> None:
        while True:
            job.stage = "loading"
            try:
                await self.engine.acquire(job.model)
                break
            except ModelBusy:
                job.stage = "waiting"      # a live stream holds another model; start when it ends
                if job.cancel:
                    return self._finish(job, "cancelled")
                await asyncio.sleep(WAIT_POLL_S)
        try:
            job.stage = "transcribing"
            detector = build_detector(VadConfig())

            def progress(reached: float, _segments: list) -> None:
                job.progress = min(0.99, reached / job.duration) if job.duration else 0.99

            segments = await asyncio.to_thread(
                transcribe_samples, samples,
                transcribe=partial(self.engine.transcribe, language=job.language, model=job.model),
                detector=detector, prompt=job.prompt, on_progress=progress, should_stop=lambda: job.cancel)
        finally:
            self.engine.release(job.model)
        if job.cancel:
            return self._finish(job, "cancelled")
        res = transcripts.result(segments, duration=job.duration, language=job.language or self.engine.last_language,
                                 model=job.model, timestamps=job.timestamps)
        if job.save:
            job.stage = "saving"
            folder = await asyncio.to_thread(
                transcripts.save, self.outputs, segments, res, title=job.label,
                source={"service": self.mod, **job.source})
            rel = f"{self.mod}/{folder.relative_to(self.outputs).as_posix()}"
            res["output"] = rel
            res["files"] = {k: f"{rel}/{n}" for k, n in
                            (("markdown", "transcript.md"), ("srt", "transcript.srt"), ("words", "words.json"))}
        job.result = res
        job.transcript = transcripts.body(segments) or "(no speech found)"
        self.done_today += 1
        self.audio_today += job.duration
        self._finish(job, "done")

    def _finish(self, job: Job, state: str) -> None:
        job.state, job.finished = state, time.time()
        if state == "done":
            job.progress = 1.0
        job.stage = state

    def _trim(self) -> None:
        old = [j for j in self.list() if j.state in ("done", "failed", "cancelled")][KEEP:]
        for j in old:
            self.jobs.pop(j.id, None)

