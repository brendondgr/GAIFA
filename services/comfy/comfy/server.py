"""The adapter's FastAPI app. Everything starts in the lifespan (no import-time work)."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from . import api_run, api_workflows, control, hub, logtail
from .client import ComfyClient, ComfyError
from .config import Settings
from .db import DB
from .library import Library
from .nodes import NodeCatalog
from .packs import Packs
from .resolve import InputError
from .run import NeedsRoom, Runner
from .tasks import Tasks

log = logging.getLogger("comfy")


async def _cancel(task: asyncio.Task) -> None:
    """Cancel and wait briefly. (A cancel that lands inside an httpx call can be swallowed, so the
    poller also has its own stop flag.)"""
    task.cancel()
    with suppress(asyncio.CancelledError, TimeoutError):
        await asyncio.wait_for(asyncio.shield(task), 5)


async def _watch(lib: Library) -> None:
    """Pick up pack edits (and saves made in ComfyUI) within a second, without a restart."""
    while True:
        try:
            lib.packs.scan()
            await lib.refresh_models()
        except Exception:  # noqa: BLE001
            log.exception("workflow scan failed")
        await asyncio.sleep(1.0)


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
        st.packs = Packs(settings.workflows, settings.comfy_view)
        st.library = Library(st.packs, st.catalog, Tasks.load(), settings.hub_url, settings.models)
        st.runner = Runner(settings, st.db, st.client, st.library, st.control)
        tasks = [asyncio.create_task(logtail.follow(settings.data / "comfyui.log")),
                 asyncio.create_task(st.control.run()),
                 asyncio.create_task(_watch(st.library)),
                 asyncio.create_task(st.runner.listen()),
                 asyncio.create_task(st.runner.loop())]
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

    @app.exception_handler(InputError)
    async def _input_error(request: Request, e: InputError):
        return JSONResponse({"detail": e.detail, "code": "invalid_input", "data": {"errors": e.errors}}, status_code=422)

    @app.exception_handler(NeedsRoom)
    async def _needs_room(request: Request, e: NeedsRoom):
        return JSONResponse({"detail": e.detail, "code": "needs_room", "data": {"plan": e.plan}}, status_code=409)

    @app.get("/health", summary="The adapter is up")
    def health() -> dict:
        return {"status": "ok"}

    app.include_router(hub.router)
    app.include_router(control.router)
    app.include_router(api_workflows.router)
    app.include_router(api_run.router)
    return app
