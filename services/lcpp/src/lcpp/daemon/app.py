"""App factory, shared state, error mapping and the static UI mount.

Errors always leave as ``{"detail", "code"}`` (the contract in docs/api.md);
the web UI maps ``code`` to field-level messages.
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from lcpp import settings as settings_mod
from lcpp.backends import Backend, make_backend
from lcpp.catalog import Catalog, CatalogError
from lcpp.instances import LcppError
from lcpp.paths import Paths
from lcpp.settings import SettingsError
from lcpp.supervisor import Supervisor

log = logging.getLogger("lcpp.daemon")


@dataclass
class State:
    paths: Paths
    settings: dict[str, Any]
    catalog: Catalog
    supervisor: Supervisor
    relay: Any = None  # lcpp.relay.RelayRegistrar once wired
    downloads: Any = None  # lcpp.downloads.Downloads
    started: float = field(default_factory=time.time)


def state(request: Request) -> State:
    return request.app.state.lcpp


def error(code: str, detail: str, status: int) -> JSONResponse:
    return JSONResponse({"detail": detail, "code": code}, status_code=status)


def create_app(paths: Paths | None = None, backend: Backend | None = None) -> FastAPI:
    paths = paths or Paths.default()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings = settings_mod.load(paths)
        catalog = Catalog.load(paths)
        sup = Supervisor(paths, backend or make_backend(paths), settings, catalog)
        st = State(paths=paths, settings=settings, catalog=catalog, supervisor=sup)
        app.state.lcpp = st
        from lcpp.downloads import Downloads
        from lcpp.relay import RelayRegistrar
        st.downloads = Downloads(paths, catalog)
        st.relay = RelayRegistrar(st)
        sup.hooks.append(st.relay)
        await st.relay.start()
        await sup.start()
        await st.relay.reconcile()
        try:
            yield
        finally:
            await st.downloads.close()
            await sup.close()
            await st.relay.close()

    app = FastAPI(title="lcpp", docs_url="/api/docs", redoc_url=None,
                  openapi_url="/api/openapi.json", lifespan=lifespan)

    @app.exception_handler(LcppError)
    async def _lcpp_error(_: Request, e: LcppError):
        return error(e.code, e.detail, e.status)

    @app.exception_handler(CatalogError)
    async def _catalog_error(_: Request, e: CatalogError):
        return error(e.code, str(e), e.status)

    @app.exception_handler(SettingsError)
    async def _settings_error(_: Request, e: SettingsError):
        return error("invalid_param", str(e), 400)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, e: RequestValidationError):
        first = e.errors()[0] if e.errors() else {}
        where = ".".join(str(p) for p in first.get("loc", []) if p != "body")
        return error("invalid_param", f"{where}: {first.get('msg', 'invalid request')}", 400)

    from lcpp.daemon.routes import chat, downloads, instances, models, relay, system

    for module in (system, instances, models, downloads, relay, chat):
        app.include_router(module.router)

    @app.get("/config.js", include_in_schema=False)
    async def config_js():
        # Served only by the daemon: its presence switches the UI from its
        # built-in mock API to this live one (a plain static server 404s it).
        return Response("window.LCPP_API_BASE = '';\n", media_type="application/javascript",
                        headers={"Cache-Control": "no-store"})

    # Catch-all static mount: must stay after every include_router above.
    if paths.web.is_dir():
        app.mount("/", StaticFiles(directory=paths.web, html=True), name="web")
    return app
