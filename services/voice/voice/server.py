"""The voice mod's HTTP routes. The realtime WebSocket is in bridge.py (`mount`)."""

from __future__ import annotations

import asyncio
import contextlib
import time
from pathlib import Path
from typing import Any, Literal

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from . import bridge, config
from .config import Settings
from .engine import Engine, EngineError
from .hub import Hub, HubError


class LoadBody(BaseModel):
    quant: Literal["q4_k_m", "q8_0"] | None = Field(None, description="The size to load; the default when left out")


class SpeechBody(BaseModel):
    text: str = Field(min_length=1, max_length=4000, description="What to say")
    voice: Literal["female", "male"] = "female"
    language: str | None = Field(None, description="A language code (en, de, …); English when left out")


class Stats:
    """Counters the status route reports (numeric stats are charted by the hub)."""

    def __init__(self) -> None:
        self.turns = 0
        self.day = time.strftime("%Y-%m-%d")
        self.first_audio_ms: list[int] = []

    def turn(self, first_audio_ms: int | None) -> None:
        if self.day != time.strftime("%Y-%m-%d"):
            self.day, self.turns = time.strftime("%Y-%m-%d"), 0
        self.turns += 1
        if first_audio_ms is not None:
            self.first_audio_ms = (self.first_audio_ms + [first_audio_ms])[-50:]

    def median_ms(self) -> int | None:
        v = sorted(self.first_audio_ms)
        return v[len(v) // 2] if v else None


def create_app(settings: Settings | None = None, hub: Hub | None = None, log_dir: Path | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    hub = hub or Hub(settings.hub_url)
    engine = Engine(settings, hub, log_dir=log_dir)
    stats = Stats()

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        async def watch() -> None:
            while True:
                await asyncio.sleep(5)
                with contextlib.suppress(Exception):
                    await engine.idle_check()

        task = asyncio.create_task(watch())
        try:
            yield
        finally:
            task.cancel()
            await engine.unload()

    app = FastAPI(title="Voice", version="0.1.0", lifespan=lifespan,
                  description="A speech-to-speech model for voice mode (LFM3-Omni-2B in llama.cpp). "
                              "Conversations run on the WebSocket /v1/realtime.")
    app.state.settings, app.state.engine, app.state.hub, app.state.stats = settings, engine, hub, stats

    @app.exception_handler(EngineError)
    async def engine_error(_: Request, e: EngineError) -> JSONResponse:
        return JSONResponse({"detail": e.detail, "code": e.code, **({"data": {"fix": e.fix}} if e.fix else {})}, e.status)

    @app.exception_handler(HubError)
    async def hub_error(_: Request, e: HubError) -> JSONResponse:
        return JSONResponse({"detail": e.detail, "code": e.code, **({"data": e.data} if e.data else {})}, e.status)

    @app.get("/health", summary="Ready")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/v1/status", summary="Whether the model is loaded, and the conversation counters")
    def status() -> dict[str, Any]:
        e = engine.status()
        loaded = e["state"] == "ready"
        return {"loaded": loaded, "busy": engine.sessions > 0 or e["state"] == "loading",
                "idle_s": round(time.time() - engine.last_used, 1),
                "memory_estimate_gb": {"q4_k_m": 4.5, "q8_0": 5.2}[engine.quant],
                "engine": e, "sessions": engine.sessions, "models": engine.models(),
                "vad": bridge.vad_kind(settings),
                "stats": [{"label": "Turns today", "value": stats.turns, "reset": "daily"},
                          *([{"label": "First audio (ms)", "value": stats.median_ms()}] if stats.median_ms() is not None else [])],
                "jobs": []}

    @app.get("/v1/models", summary="The sizes of the model on disk, and which is loaded")
    def models() -> dict[str, Any]:
        return {"model": config.MODEL, "repo": config.REPO, "folder": str(settings.folder), "models": engine.models(),
                "voices": list(config.VOICES)}

    @app.post("/v1/load", summary="Load the model (asks GAIFA for memory first); a different size replaces the loaded one")
    async def load(request: Request, body: LoadBody | None = None) -> dict[str, Any]:
        room = request.headers.get("x-gaifa-make-room", "").strip().lower() in ("1", "true", "yes") or \
            request.query_params.get("make_room") in ("1", "true")
        return await engine.load(body.quant if body else None, make_room=room)

    @app.post("/v1/unload", summary="Stop llama.cpp and free the model's memory")
    async def unload() -> dict[str, Any]:
        if engine.sessions:
            raise EngineError(409, "a conversation is open: end it first", "busy")
        return await engine.unload()

    @app.post("/v1/speech", summary="Say a text with the model's own voice (WAV, 24 kHz mono)", response_class=Response,
              responses={200: {"content": {"audio/wav": {}}}})
    async def speech(body: SpeechBody) -> Response:
        port = await engine.ensure()
        req = {"input": body.text, "voice": body.voice, "response_format": "wav", **({"lang": body.language} if body.language else {})}
        async with httpx.AsyncClient(timeout=httpx.Timeout(10, read=120)) as c:
            r = await c.post(f"http://127.0.0.1:{port}/tts", json=req)
        if r.status_code >= 400:
            raise EngineError(502, f"llama.cpp answered HTTP {r.status_code}: {r.text[:200]}", "speech_failed")
        engine.touch()
        return Response(r.content, media_type="audio/wav")

    bridge.mount(app)
    return app
