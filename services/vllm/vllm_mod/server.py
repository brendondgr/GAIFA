"""The adapter's FastAPI app. Everything starts in the lifespan (no import-time work)."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from .profiles import load_profiles
from .settings import Settings

log = logging.getLogger("vllm")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logging.basicConfig(level=logging.INFO, format="%(levelname)s:     %(message)s")
        logging.getLogger("httpx").setLevel(logging.WARNING)
        app.state.settings = settings
        settings.state_dir.mkdir(parents=True, exist_ok=True)
        yield

    app = FastAPI(title="vLLM", version="0.1.0", lifespan=lifespan,
                  description="Runs vLLM in kyuz0's gfx1151 image, one model profile at a time.")

    @app.get("/health")
    def health() -> dict:
        """AIHub polls this: the adapter is up (the engine's own state is in /v1/status)."""
        return {"status": "ok"}

    @app.get("/v1/profiles", summary="The model profiles")
    def profiles(request: Request) -> dict:
        found, problems = load_profiles(request.app.state.settings.profiles_dir)
        return {"profiles": [p.model_dump() for p in found.values()], "problems": problems}

    @app.get("/v1/status", summary="Load state, stats and jobs (architecture §4.6)")
    def status() -> dict:
        return {"loaded": False, "busy": False, "idle_s": None, "stats": [], "jobs": []}

    return app
