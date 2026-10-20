"""The stt mod's HTTP routes (plan Phase 29)."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import time
import uuid
from datetime import date
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import catalog
from .config import Settings
from .engine import Engine
from .hub import Hub
from .jobs import TMP, Jobs

logger = logging.getLogger(__name__)

Preset = Literal["fast", "balanced", "accurate", "best"]
Model = Literal["tiny", "base", "small", "medium", "large-v3-turbo", "large-v3"]
Timestamps = Literal["none", "segments", "words"]
MAX_UPLOAD = 4 << 30
PRESET_HELP = ("fast = base, balanced = small (the default), accurate = large-v3-turbo, best = large-v3. "
               "Ignored when `model` is given.")


class TranscribeRequest(BaseModel):
    output_id: str = Field(description="The recording: output:<id> of an audio or video output (video is "
                                       "transcribed from its audio track)",
                           json_schema_extra={"format": "aihub-file", "x-kind": "audio"})
    preset: Preset | None = Field(None, description=PRESET_HELP)
    model: Model | None = Field(None, description="A model by name, instead of a preset")
    language: str | None = Field(None, description="ISO code such as en or de; left out, it is detected")
    prompt: str | None = Field(None, max_length=800, description="Names and terms to expect (biases spelling)")
    timestamps: Timestamps = Field("segments", description="In the result: none, segments, or words (the saved "
                                                           "words.json always has word times)")
    title: str | None = Field(None, max_length=80, description="Names the transcript (default: the output's title)")
    save: bool = Field(True, description="Save the transcript as an output (.md, .srt, words.json)")


class LoadRequest(BaseModel):
    preset: Preset | None = Field(None, description=PRESET_HELP)
    model: Model | None = Field(None, description="A model by name, instead of a preset")


def http_error(status: int, detail: str, code: str, fix: str | None = None) -> HTTPException:
    return HTTPException(status, {"detail": detail, "code": code, **({"fix": fix} if fix else {})})


def create_app(settings: Settings | None = None, *, engine: Engine | None = None, hub: Hub | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    hub = hub or Hub(settings.hub_url)
    engine = engine or Engine(settings, registrar=hub.register_model)
    jobs = Jobs(engine, hub, settings.outputs)

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        tasks = [asyncio.create_task(jobs.run()), asyncio.create_task(engine.idle_loop()),
                 asyncio.create_task(hub.register_present(settings.weights))]
        try:
            yield
        finally:
            for t in tasks:
                t.cancel()
            await engine.unload()

    app = FastAPI(title="Speech to Text", version="0.1.0", lifespan=lifespan,
                  description="Speech to text with faster-whisper (CTranslate2), ported from the TranscriberPrototype.")
    app.state.engine, app.state.jobs, app.state.settings, app.state.hub = engine, jobs, settings, hub
    day = {"date": date.today()}

    @app.get("/health", summary="Ready when the server answers (the model loads on demand)")
    def health() -> dict:
        return {"status": "ok", "model": engine.state}

    @app.get("/v1/status", summary="Loaded model, jobs and today's numbers (architecture §4.6)")
    def status() -> dict:
        if day["date"] != date.today():
            day["date"], jobs.done_today, jobs.audio_today = date.today(), 0, 0.0
        info = catalog.BY_NAME.get(engine.model or "")
        rtf = engine.inference_seconds / engine.audio_seconds if engine.audio_seconds else None
        live = [j for j in jobs.list() if j.state in ("queued", "running")]
        recent = [j for j in jobs.list() if j.state not in ("queued", "running") and j.finished
                  and time.time() - j.finished < 600]
        return {
            "loaded": engine.model if engine.ready else None,
            "busy": engine.busy or bool(live),
            "idle_s": round(time.monotonic() - engine.last_used, 1),
            "memory_estimate_gb": info.memory_gb if info else None,
            "engine": engine.describe(),
            "stats": [
                {"label": "Transcripts today", "value": jobs.done_today, "reset": "daily"},
                {"label": "Audio today (min)", "value": round(jobs.audio_today / 60, 1), "reset": "daily"},
                {"label": "Real-time factor", "value": round(rtf, 4) if rtf is not None else "—"},
                {"label": "Model", "value": f"{engine.model} · {engine.device}" if engine.ready else "none"},
            ],
            "jobs": [{"id": j.id, "label": j.label, "progress": j.progress, "state": j.state,
                      "route": "#/s/stt/transcribe"} for j in live + recent[:5]],
        }

    @app.get("/v1/models", summary="The models: size, downloaded, loaded, and the device and precision each runs at")
    async def models() -> dict:
        gpu = await engine.gpu()
        return {"models": catalog.describe(settings.weights, loaded=engine.model if engine.ready else None, gpu=gpu),
                "presets": catalog.PRESETS, "default": catalog.PRESETS[catalog.DEFAULT_PRESET],
                "gpu": gpu, "engine": engine.describe()}

    @app.post("/v1/load", summary="Load a model (fetching its weights first if needed); default: balanced (small)")
    async def load(body: LoadRequest | None = None) -> dict:
        body = body or LoadRequest()
        name = catalog.pick(body.model, body.preset)
        try:
            await engine.ensure(name)
        except Exception as exc:  # noqa: BLE001
            raise http_error(500, f"couldn't load {name}: {exc}", "load_failed",
                             "try a smaller model, or check `aihub logs stt`") from exc
        return engine.describe()

    @app.post("/v1/unload", summary="Unload the model (its process exits, freeing the memory)")
    async def unload() -> dict:
        await engine.unload()
        return engine.describe()

    @app.post("/v1/transcribe", status_code=202, summary="Transcribe an audio or video output (a job)")
    async def transcribe(body: TranscribeRequest) -> dict:
        """Starts a job; poll `GET /v1/jobs/{id}`. Done → `result` = {text, language, duration, segments,
        output, files}: the transcript is saved as one output (transcript.md with [mm:ss] marks, .srt, words.json)."""
        if not re.fullmatch(r"(output:)?[A-Za-z0-9_.:-]{1,120}", body.output_id.strip()):
            raise http_error(422, "output_id must be output:<id> of an audio or video output", "invalid_input")
        job = jobs.submit(label=body.title or "audio", model=body.model, preset=body.preset, language=body.language,
                          prompt=body.prompt, timestamps=body.timestamps, save=body.save,
                          source={"output_id": body.output_id.strip()})
        return job.view()

    @app.post("/v1/transcribe/upload", status_code=202, summary="Transcribe a file sent as the raw request body (a job)",
              openapi_extra={"requestBody": {"required": True, "content": {
                  "application/octet-stream": {"schema": {"type": "string", "format": "binary"}}}}})
    async def transcribe_upload(
        request: Request,
        filename: str = Query("upload.wav", max_length=200, description="The file's name (its extension helps)"),
        preset: Preset | None = Query(None, description=PRESET_HELP),
        model: Model | None = Query(None, description="A model by name, instead of a preset"),
        language: str | None = Query(None, description="ISO code; left out, it is detected"),
        prompt: str | None = Query(None, max_length=800, description="Names and terms to expect"),
        timestamps: Timestamps = Query("segments"),
        save: bool = Query(True, description="Save the transcript as an output"),
    ) -> dict:
        safe = re.sub(r"[^A-Za-z0-9._-]+", "-", filename).strip("-.") or "upload.wav"
        TMP.mkdir(parents=True, exist_ok=True)
        path = TMP / f"upload-{uuid.uuid4().hex[:10]}-{safe}"
        size = 0
        with path.open("wb") as f:
            async for chunk in request.stream():
                size += len(chunk)
                if size > MAX_UPLOAD:
                    f.close()
                    path.unlink(missing_ok=True)
                    raise http_error(413, "the file is larger than 4 GB", "too_large")
                f.write(chunk)
        if size == 0:
            path.unlink(missing_ok=True)
            raise http_error(422, "the body is empty; send the file's bytes", "invalid_input")
        stem = safe.rsplit(".", 1)[0].replace("-", " ").replace("_", " ")
        job = jobs.submit(label=stem, model=model, preset=preset, language=language, prompt=prompt,
                          timestamps=timestamps, save=save, source={"upload": safe}, upload=path)
        return job.view()

    @app.get("/v1/jobs", summary="Recent transcription jobs, newest first")
    def list_jobs() -> dict:
        return {"jobs": [j.view() for j in jobs.list()]}

    @app.get("/v1/jobs/{jid}", summary="One job: state, progress, and when done its result")
    def get_job(jid: str) -> dict:
        job = jobs.get(jid)
        if job is None:
            raise http_error(404, f"no job {jid!r}", "not_found")
        return job.view()

    @app.post("/v1/jobs/{jid}/cancel", summary="Cancel a queued or running job")
    def cancel_job(jid: str) -> dict:
        job = jobs.cancel(jid)
        if job is None:
            raise http_error(404, f"no job {jid!r}", "not_found")
        return job.view()

    @app.exception_handler(catalog.UnknownModel)
    async def unknown_model(_: Request, exc: catalog.UnknownModel) -> JSONResponse:
        return JSONResponse({"detail": str(exc), "code": "invalid_input",
                             "fix": f"presets: {', '.join(catalog.PRESETS)}; models: {', '.join(catalog.BY_NAME)}"}, 422)

    @app.exception_handler(HTTPException)
    async def envelope(_: Request, exc: HTTPException) -> JSONResponse:
        body: Any = exc.detail if isinstance(exc.detail, dict) else {"detail": exc.detail, "code": "error"}
        return JSONResponse(body, exc.status_code)

    return app
