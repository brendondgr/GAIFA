"""The adapter's FastAPI app. Everything starts in the lifespan (no import-time work)."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI

from . import hub, logtail
from .config import Settings
from .db import DB


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = settings
        app.state.db = DB(settings.db)
        tail = asyncio.create_task(logtail.follow(settings.data / "comfyui.log"))
        try:
            yield
        finally:
            tail.cancel()
            with suppress(asyncio.CancelledError):
                await tail
            app.state.db.close()

    app = FastAPI(title="Images & Video (ComfyUI)", version="0.1.0", lifespan=lifespan)

    @app.get("/health", summary="The adapter is up")
    def health() -> dict:
        return {"status": "ok"}

    app.include_router(hub.router)
    return app
