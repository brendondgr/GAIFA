"""File transcription jobs, one at a time: input → canonical audio → pause-cut chunks → outputs."""

from __future__ import annotations

import asyncio
import logging
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
from .engine import Engine
from .hub import Hub, HubError
from .vad import build_detector

logger = logging.getLogger(__name__)

TMP = MOD_DIR / "runtime" / "tmp"
KEEP = 50                    # finished jobs remembered


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
    stage: str = "queued"     # fetching | decoding | loading | transcribing | saving
    progress: float = 0.0
    created: float = field(default_factory=time.time)
    started: float | None = None
    finished: float | None = None
    duration: float | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
    cancel: bool = False

    def view(self) -> dict[str, Any]:
        out = {"id": self.id, "label": self.label, "state": self.state, "stage": self.stage,
               "progress": round(self.progress, 3), "model": self.model, "language": self.language,
               "created": self.created, "started": self.started, "finished": self.finished,
               "duration": self.duration, "source": self.source, "error": self.error}
        if self.result is not None:
            out["result"] = self.result
        if self.started and self.finished and self.duration:
            out["rtf"] = round((self.finished - self.started) / self.duration, 4)
        return out


class Jobs:
    def __init__(self, engine: Engine, hub: Hub, outputs: Path, mod: str = "stt") -> None:
        self.engine, self.hub, self.outputs, self.mod = engine, hub, outputs, mod
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
        return job

    async def run(self) -> None:
        while True:
            job = await self._queue.get()
            if job.state != "queued":
                continue
            try:
                await self._run(job)
            except Exception as exc:  # noqa: BLE001 - one bad file never stops the queue
                logger.exception("Job %s failed", job.id)
                job.error = str(exc) or type(exc).__name__
                self._finish(job, "failed")
            finally:
                if job.upload is not None:
                    job.upload.unlink(missing_ok=True)

    async def _run(self, job: Job) -> None:
        job.state, job.started = "running", time.time()
        work = TMP / job.id
        try:
            path = job.upload
            if path is None:
                job.stage = "fetching"
                try:
                    path, record = await self.hub.fetch_output(job.source["output_id"], work, "input")
                except HubError as exc:
                    raise ValueError(str(exc)) from exc
                if job.label in ("", "audio"):
                    job.label = str(record.get("title") or job.label)[:80]
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
        job.stage = "loading"
        await self.engine.ensure(job.model)
        job.stage = "transcribing"
        detector = build_detector(VadConfig())

        def progress(reached: float, _segments: list) -> None:
            job.progress = min(0.99, reached / job.duration) if job.duration else 0.99

        segments = await asyncio.to_thread(
            transcribe_samples, samples,
            transcribe=partial(self.engine.transcribe, language=job.language),
            detector=detector, prompt=job.prompt, on_progress=progress, should_stop=lambda: job.cancel)
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

