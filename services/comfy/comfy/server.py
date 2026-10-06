"""The adapter's FastAPI app. Everything starts in the lifespan (no import-time work)."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from . import hub
from .config import Settings
from .db import DB


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = settings
        app.state.db = DB(settings.db)
        try:
            yield
        finally:
            app.state.db.close()

    app = FastAPI(title="Images & Video (ComfyUI)", version="0.1.0", lifespan=lifespan)

    @app.get("/health", summary="The adapter is up")
    def health() -> dict:
        return {"status": "ok"}

    app.include_router(hub.router)
    return app
