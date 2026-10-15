"""The adapter's FastAPI app. Everything starts in the lifespan (no import-time work)."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .engine import Engine, EngineError
from .hubclient import Hub, NeedsRoom
from .profiles import load_profiles
from .settings import Settings

log = logging.getLogger("vllm")
YES = {"1", "true", "yes"}


class LoadRequest(BaseModel):
    profile: str | None = Field(None, description="A profile id (default: the loaded one, else the last loaded)")


def create_app(settings: Settings | None = None, engine: Engine | None = None) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logging.basicConfig(level=logging.INFO, format="%(levelname)s:     %(message)s")
        logging.getLogger("httpx").setLevel(logging.WARNING)
        settings.state_dir.mkdir(parents=True, exist_ok=True)
        st = app.state
        st.settings = settings
        st.engine = engine or Engine(settings, Hub(settings.hub_url))
        await st.engine.adopt()
        try:
            yield
        finally:
            await st.engine.shutdown(stop_engine=getattr(st, "stop_engine_on_exit", True))

    app = FastAPI(title="vLLM", version="0.1.0", lifespan=lifespan,
                  description="Runs vLLM in kyuz0's gfx1151 image, one model profile at a time.")

    @app.exception_handler(EngineError)
    async def _engine_error(_: Request, e: EngineError) -> JSONResponse:
        return JSONResponse({"detail": e.detail, "code": e.code, "data": e.data}, e.status)

    @app.exception_handler(NeedsRoom)
    async def _needs_room(_: Request, e: NeedsRoom) -> JSONResponse:
        return JSONResponse(e.body, 409)          # the hub's body: {detail, code: needs_room, data: {plan}}

    @app.get("/health")
    def health() -> dict:
        """AIHub polls this: the adapter is up (the engine's own state is in /v1/status)."""
        return {"status": "ok"}

    @app.get("/v1/profiles", summary="The model profiles")
    def profiles(request: Request) -> dict:
        found, problems = load_profiles(request.app.state.settings.profiles_dir)
        eng: Engine = request.app.state.engine
        return {"profiles": [p.model_dump() for p in found.values()], "problems": problems,
                "loaded": eng.profile.id if eng.profile else None, "last": eng.last_profile()}

    @app.post("/v1/load", summary="Start vLLM with a profile (stops the running one first)")
    async def load(request: Request, body: LoadRequest | None = None,
                   wait: bool = Query(True, description="Answer once vLLM is ready (else at once)"),
                   make_room: bool = Query(False, description="Let AIHub unload idle mods for the memory")) -> dict:
        room = make_room or request.headers.get("x-aihub-make-room", "").strip().lower() in YES
        return await request.app.state.engine.load(body.profile if body else None, make_room=room, wait=wait)

    @app.post("/v1/unload", summary="Stop vLLM")
    async def unload(request: Request) -> dict:
        return await request.app.state.engine.unload()

    @app.get("/v1/engine", summary="The engine: state, stage, profile, command line")
    def engine_view(request: Request) -> dict:
        return request.app.state.engine.view()

    @app.get("/v1/engine/logs", summary="The engine's last log lines")
    def engine_logs(request: Request, tail: int = Query(200, ge=1, le=500)) -> dict:
        return {"lines": list(request.app.state.engine.lines)[-tail:]}

    @app.get("/v1/status", summary="Load state, stats and jobs (architecture §4.6)")
    def status(request: Request) -> dict:
        eng: Engine = request.app.state.engine
        p = eng.default_profile()
        return {"loaded": eng.state == "ready", "busy": False, "idle_s": None,
                "memory_estimate_gb": eng.needs_gb(p) if p else None, "stats": [], "jobs": []}

    return app
