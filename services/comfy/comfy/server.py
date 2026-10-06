"""The adapter's FastAPI app. Everything starts in the lifespan (no import-time work)."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from . import control, hub, logtail
from .client import ComfyClient, ComfyError
from .config import Settings
from .db import DB
from .nodes import NodeCatalog

log = logging.getLogger("comfy")


async def _cancel(task: asyncio.Task) -> None:
    """Cancel and wait briefly. (A cancel that lands inside an httpx call can be swallowed, so the
    poller also has its own stop flag.)"""
    task.cancel()
    with suppress(asyncio.CancelledError, TimeoutError):
        await asyncio.wait_for(asyncio.shield(task), 5)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logging.basicConfig(level=logging.INFO, format="%(levelname)s:     %(message)s")
        st = app.state
        st.settings = settings
        st.db = DB(settings.db)
        st.client = ComfyClient(settings.comfy_url)
        st.catalog = NodeCatalog.load(settings.data / "object_info.json")
        st.control = control.Controller(st.client, st.catalog, str(settings.control),
                                        settings.load_timeout_s, settings.idle_unload_s)
        tasks = [asyncio.create_task(logtail.follow(settings.data / "comfyui.log")),
                 asyncio.create_task(st.control.run())]
        try:
            yield
        finally:
            st.control.stop()
            for t in tasks:
                await _cancel(t)
            if settings.quit_on_exit:
                with suppress(Exception):
                    q = await st.client.queue() if await st.client.up() else None
                    if q is not None and not (q.get("queue_running") or q.get("queue_pending")):
                        log.info("adapter stopping: stopping the idle ComfyUI too")
                        await st.control.unload()
            await st.client.close()
            st.db.close()

    app = FastAPI(title="Images & Video (ComfyUI)", version="0.1.0", lifespan=lifespan)

    @app.exception_handler(ComfyError)
    async def _comfy_error(request: Request, e: ComfyError):
        return JSONResponse({"detail": e.detail, "code": "comfyui", "data": e.data}, status_code=e.status)

    @app.get("/health", summary="The adapter is up")
    def health() -> dict:
        return {"status": "ok"}

    app.include_router(hub.router)
    app.include_router(control.router)
    return app
