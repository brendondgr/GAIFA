"""The hub's FastAPI app: `create_app()`, the lifespan and the error envelope.

Nothing happens at import time. The lifespan starts subsystems in the order
in architecture §5 and stops them in reverse. Each area's router marks the
area live (`Hub.mark_live`) so `/config.js` can tell the UI which areas are
backed by real data.
"""

from __future__ import annotations

import logging
import os
import time
import tomllib
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from utils.config import Config
from utils.db import Database
from utils.events import SSE_PING_S, ActivityLog, Alerts, EventBus
from utils.paths import DEFAULT_ROOT, Paths
from utils.registry import Registry, RegistryError
from utils.registry.verify import Verifier
from utils.services import ServiceError, ServiceManager

DEMO_MODS = DEFAULT_ROOT / "utils" / "tests" / "fixtures" / "mods"

log = logging.getLogger("aihub")

STATUS_CODES = {400: "bad_request", 404: "not_found", 405: "method_not_allowed", 409: "conflict", 422: "invalid_request"}


class HubError(Exception):
    """An error the UI understands: `{detail, code, data?}` with an HTTP status (brief §6.3)."""

    def __init__(self, status: int, code: str, detail: str, data: dict[str, Any] | None = None) -> None:
        super().__init__(detail)
        self.status, self.code, self.detail, self.data = status, code, detail, data


@dataclass
class Options:
    """What `app.py` was started with."""

    port: int | None = None  # None = config hub.port
    dev: bool = False  # subprocess backend instead of systemd
    autostart: bool = True
    demo_mods: bool = False  # also load utils/tests/fixtures/mods/


@dataclass
class Hub:
    """Everything the routes need, on `app.state.hub`."""

    paths: Paths
    config: Config
    backend: Any
    options: Options
    version: str
    started_ts: float = field(default_factory=time.time)
    bus: EventBus = field(default_factory=EventBus)
    db: Database | None = None
    activity: ActivityLog | None = None
    alerts: Alerts | None = None
    registry: Registry | None = None
    services: ServiceManager | None = None
    timing: Any = None  # services.Timing; tests shorten it
    live_areas: list[str] = field(default_factory=list)
    sse_ping_s: float = SSE_PING_S

    @property
    def port(self) -> int:
        return self.options.port or self.config.hub.port

    def mark_live(self, area: str) -> None:
        if area not in self.live_areas:
            self.live_areas.append(area)


def hub_version() -> str:
    try:
        return tomllib.loads((DEFAULT_ROOT / "pyproject.toml").read_text())["project"]["version"]
    except (OSError, KeyError, tomllib.TOMLDecodeError):
        return "0.0.0"


def default_backend(options: Options) -> Any:
    """systemd units normally; child processes with `--dev` or where there is no systemd user manager."""
    from utils.backends import systemd
    from utils.backends.subprocess import SubprocessBackend

    if options.dev:
        return SubprocessBackend()
    if systemd.available():
        return systemd.SystemdBackend()
    log.warning("no systemd user manager: running mods as child processes (they stop with the hub)")
    return SubprocessBackend()


def create_app(paths: Paths, config: Config, backend: Any = None, options: Options | None = None) -> FastAPI:
    from utils import proxy
    from utils.routes import events, models, services, system, web

    options = options or Options()
    hub = Hub(paths=paths, config=config, backend=backend or default_backend(options), options=options, version=hub_version())

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with AsyncExitStack() as stack:
            # 1. config: already validated; create the derived dirs.
            paths.ensure()
            # 2. db
            hub.db = Database(paths.hub_db)
            hub.db.open()
            stack.callback(hub.db.close)
            # 3. event bus, activity log, alerts
            stack.callback(hub.bus.close)
            hub.activity = ActivityLog(hub.db, hub.bus)
            await hub.activity.load()
            hub.alerts = Alerts(hub.bus)
            # 4. models registry: load registry.json (status is computed when read).
            hub.registry = Registry(paths, hub.bus, hub.activity, hub.alerts)
            hub.registry.load()
            verifier = Verifier(hub.registry)
            verifier.start()
            stack.push_async_callback(verifier.close)
            # 5. services: find manifests, adopt running units, autostart in the background.
            hub.services = ServiceManager(
                paths, hub.config, hub.backend, hub.bus, hub.activity, hub.alerts, hub.port,
                extra_dirs=[DEMO_MODS] if hub.options.demo_mods else [], timing=hub.timing,
            )
            stack.push_async_callback(hub.services.close)
            await hub.services.boot(autostart=hub.options.autostart)
            hub.registry.services = hub.services
            # 6–8 (outputs, memory, metrics) arrive in Phases 4–6.
            log.info("AIHub %s ready on port %s (root %s)", hub.version, hub.port, paths.root)
            yield

    app = FastAPI(
        title="AIHub",
        version=hub.version,
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.state.hub = hub
    _error_handlers(app)

    app.include_router(system.router)
    hub.mark_live("system")
    app.include_router(events.router)
    app.include_router(services.router)
    app.include_router(proxy.router)
    app.include_router(models.router)
    for area in ("services", "logs", "operations", "proxy", "events"):
        hub.mark_live(area)

    app.include_router(web.router)
    app.mount("/", WebFiles(directory=paths.web, html=True, check_dir=False), name="web")
    return app


class WebFiles(StaticFiles):
    """`web/` as static files; a missing folder is a 404, not a crash."""

    async def check_config(self) -> None:
        if os.path.isdir(self.directory):
            await super().check_config()

    async def get_response(self, path: str, scope: Any) -> Any:
        if not os.path.isdir(self.directory):
            raise StarletteHTTPException(404)
        resp = await super().get_response(path, scope)
        # Revalidate every time (a cheap 304 via the ETag): without this, browsers keep running
        # an old api.js / mock.js after the hub is upgraded.
        resp.headers["Cache-Control"] = "no-cache"
        return resp


def _envelope(status: int, code: str, detail: str, data: Any = None) -> JSONResponse:
    body: dict[str, Any] = {"detail": detail, "code": code}
    if data is not None:
        body["data"] = data
    # Marks the hub's own errors, so the UI can tell them from a mod's proxied error responses.
    return JSONResponse(body, status_code=status, headers={"X-AIHub-Error": code})


def _error_handlers(app: FastAPI) -> None:
    @app.exception_handler(HubError)
    async def _hub_error(_: Request, e: HubError) -> JSONResponse:
        return _envelope(e.status, e.code, e.detail, e.data)

    @app.exception_handler(ServiceError)
    async def _service_error(_: Request, e: ServiceError) -> JSONResponse:
        return _envelope(e.status, e.code, e.detail, e.data)

    @app.exception_handler(RegistryError)
    async def _registry_error(_: Request, e: RegistryError) -> JSONResponse:
        return _envelope(e.status, e.code, e.detail, e.data)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, e: StarletteHTTPException) -> JSONResponse:
        detail = e.detail if isinstance(e.detail, str) else "error"
        resp = _envelope(e.status_code, STATUS_CODES.get(e.status_code, "hub_error"), detail)
        if e.headers:
            resp.headers.update(e.headers)
        return resp

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, e: RequestValidationError) -> JSONResponse:
        errors = [{"loc": list(x["loc"]), "msg": x["msg"]} for x in e.errors()]
        first = errors[0] if errors else {"loc": [], "msg": "invalid request"}
        detail = f"{'.'.join(str(p) for p in first['loc'])}: {first['msg']}"
        return _envelope(422, "invalid_request", detail, {"errors": errors})

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, e: Exception) -> JSONResponse:
        log.exception("unhandled error")
        return _envelope(500, "hub_error", f"{type(e).__name__}: {e}")

