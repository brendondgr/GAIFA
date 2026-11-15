"""The hub's FastAPI app: `create_app()`, the lifespan and the error envelope.

Nothing happens at import time. The lifespan starts subsystems in the order
in architecture §5 and stops them in reverse. Each area's router marks the
area live (`Hub.mark_live`) so `/config.js` can tell the UI which areas are
backed by real data.
"""

from __future__ import annotations

import asyncio
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
from utils.memory import MemoryManager
from utils.memory.triggers import hook as memory_hook
from utils.metrics import MetricsError, Recorder
from utils.origin import LOOPBACK_HOSTS, RequestGuard
from utils.outputs import OutputError, Outputs
from utils.outputs.watch import Watcher as OutputsWatcher
from utils.paths import DEFAULT_ROOT, Paths
from utils.registry import Registry, RegistryError
from utils.registry.alerts import Watcher as RegistryWatcher
from utils.registry.docs_hook import DocsHook
from utils.registry.verify import Verifier
from utils.services import ServiceError, ServiceManager
from utils.widgets import Widgets

DEMO_MODS = DEFAULT_ROOT / "utils" / "tests" / "fixtures" / "mods"

log = logging.getLogger("gaifa")

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
    extra_hosts: tuple[str, ...] = ()  # Host names allowed besides loopback: only the tests' ASGI clients (`http://hub`)
    setup_runner: Any = None  # capability-enablement 3.1: tests' fake `gaifa` for setup jobs (utils/setup_jobs.py)


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
    config_lock: asyncio.Lock = field(default_factory=asyncio.Lock)   # config.toml saves, one at a time (settings-that-stick 2.1)
    db: Database | None = None
    activity: ActivityLog | None = None
    alerts: Alerts | None = None
    registry: Registry | None = None
    outputs: Outputs | None = None
    memory: MemoryManager | None = None
    memory_source: Any = None  # tests inject a fake (utils/memory/source.py)
    memory_every_s: float = 2.0
    gpu: Any = None         # gpu.GpuQueue (plan 31.1)
    metrics: Recorder | None = None
    metrics_every_s: float = 10.0
    widgets: Widgets | None = None
    tools: Any = None       # tools.catalog.Catalog
    approvals: Any = None   # tools.approvals.Approvals
    grants: Any = None      # tools.grants.Grants (plan 25.2)
    calls: Any = None       # tools.calls.Calls
    sessions: Any = None    # sessions.Sessions
    prefs: Any = None       # prefs.Prefs (plan 21.2)
    repos: Any = None       # repos_watch.RepoWatcher (plan mod-repos 3.3)
    setup: Any = None       # setup_jobs.SetupJobs (capability-enablement 3.1)
    ui_store: Any = None    # ui_store.UiStore, made on first use (settings-that-stick 4.1)
    services: ServiceManager | None = None
    timing: Any = None  # services.Timing; tests shorten it
    live_areas: list[str] = field(default_factory=list)
    sse_ping_s: float = SSE_PING_S

    listen_port: int | None = None  # fixed when the app is built: a saved hub.port applies at the next start
    allowed_hosts: frozenset[str] = LOOPBACK_HOSTS  # Host header names the hub answers (utils/origin.py)
    lan: Any = None  # utils.lan.Lan: other devices on the network (plan lan-access)
    exit_code: int = 0  # 75 after POST /api/system/restart: the unit starts the hub again
    stop_server: Any = None  # app.py's Server.stop, for that route

    @property
    def port(self) -> int:
        return self.listen_port or self.options.port or self.config.hub.port

    def mark_live(self, area: str) -> None:
        if area not in self.live_areas:
            self.live_areas.append(area)


def hub_version() -> str:
    try:
        return tomllib.loads((DEFAULT_ROOT / "pyproject.toml").read_text())["project"]["version"]
    except (OSError, KeyError, tomllib.TOMLDecodeError):
        return "0.0.0"


def default_backend(options: Options, config: Config | None = None, paths: Paths | None = None) -> Any:
    """`[hub] backend` (plan 37.1): `auto` is systemd units where there's a systemd user manager, else
    detached processes that outlive the hub (macOS); `--dev` always runs mods as child processes."""
    from utils.backends import systemd
    from utils.backends.detached import DetachedBackend
    from utils.backends.subprocess import SubprocessBackend

    want = config.hub.backend if config else "auto"
    if options.dev or want == "subprocess":
        return SubprocessBackend()
    if want == "systemd" or (want == "auto" and systemd.available()):
        return systemd.SystemdBackend()
    if paths is None:
        log.warning("no state folder for detached mods: running them as child processes (they stop with the hub)")
        return SubprocessBackend()
    if want == "auto":
        log.info("no systemd user manager: mods run as detached processes (data/state/hub/pids/)")
    return DetachedBackend(paths.state / "hub" / "pids")


def create_app(paths: Paths, config: Config, backend: Any = None, options: Options | None = None) -> FastAPI:
    from utils import proxy
    from utils.lan import Lan
    from utils.routes import events, gpu, lan, llm, mcp, memory, mentions, metrics, models, notify, outputs, overview, prefs, repos, services, sessions, settings, setup, skills, system, tools, ui_store, web, webpages, widgets

    options = options or Options()
    hub = Hub(paths=paths, config=config, backend=backend or default_backend(options, config, paths), options=options, version=hub_version())
    hub.listen_port = hub.port
    hub.allowed_hosts = LOOPBACK_HOSTS | {h.lower() for h in options.extra_hosts}
    hub.lan = Lan(config.hub.lan, paths.state, hub.port)          # other devices on the network (plan lan-access)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with AsyncExitStack() as stack:
            # 1. config: already validated; create the derived dirs.
            paths.ensure()
            # 1b. the hub's own log file (plan 16.1)
            from utils.logfiles import LogFiles, hub_handler

            fh = hub_handler(paths.logs)
            for name in ("", "uvicorn.error"):
                logging.getLogger(name).addHandler(fh)

            def _close_log() -> None:
                for name in ("", "uvicorn.error"):
                    logging.getLogger(name).removeHandler(fh)
                fh.close()

            stack.callback(_close_log)
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
            watcher = RegistryWatcher(hub.registry)
            watcher.start()
            stack.push_async_callback(watcher.close)
            verifier = Verifier(hub.registry)
            verifier.start()
            stack.push_async_callback(verifier.close)
            docs_hook = DocsHook(hub.registry, paths.root, lambda: hub.config.docs.regenerate)
            docs_hook.start()
            stack.push_async_callback(docs_hook.close)
            # 5. services: find manifests, adopt running units, autostart in the background.
            hub.services = ServiceManager(
                paths, hub.config, hub.backend, hub.bus, hub.activity, hub.alerts, hub.port,
                extra_dirs=[DEMO_MODS] if hub.options.demo_mods else [], timing=hub.timing,
            )
            stack.push_async_callback(hub.services.close)
            # mods' output → data/logs/<id>.log, followed from the start (plan 16.1)
            hub.services.logfiles = LogFiles(paths.logs)
            hub.services.logfiles.backend = hub.backend
            stack.push_async_callback(hub.services.logfiles.close)

            async def ship(svc: Any) -> None:
                if not svc.external:
                    hub.services.logfiles.ship(svc.id)

            hub.services.on_ready.append(ship)
            await hub.services.boot(autostart=hub.options.autostart)
            for svc in hub.services.list():
                if svc.up and not svc.external:
                    hub.services.logfiles.ship(svc.id)
            hub.registry.services = hub.services
            hub.services.registry = hub.registry
            # 6. outputs: the index, then watch outputs/ (the startup rescan runs in the background).
            hub.outputs = Outputs(paths, hub.db, hub.bus, hub.activity)
            hub.outputs.start()
            stack.push_async_callback(hub.outputs.close)
            out_watcher = OutputsWatcher(hub.outputs, hub.alerts, name_of=_service_name(hub),
                                         hidden_keep_days=lambda: hub.config.outputs.hidden_keep_days)
            out_watcher.start()
            stack.push_async_callback(out_watcher.close)
            # 7. memory: sample every 2 s; loads, proxied triggers and acquire go through it.
            hub.memory = MemoryManager(hub.services, hub.db, hub.bus, hub.alerts, hub.activity,
                                       source=hub.memory_source, every=hub.memory_every_s)
            hub.services.memory = hub.memory
            hub.services.before_proxy.append(memory_hook(hub.memory, lambda: hub.gpu))
            await hub.memory.start()
            stack.push_async_callback(hub.memory.close)
            # 7b. the GPU queue (plan 31.1): mods take the slot around their GPU work, then ask for memory.
            from utils.gpu import GpuQueue

            hub.gpu = GpuQueue(hub.bus, hub.alerts, hub.activity, cfg=lambda: hub.config.gpu, name_of=_service_name(hub))
            await hub.gpu.start()
            stack.push_async_callback(hub.gpu.close)
            # 8. metrics: record every 10 s and follow service and job events; roll up hourly.
            hub.metrics = Recorder(hub.services, hub.memory, hub.db, hub.bus, hub.alerts,
                                   disk_path=paths.root, every=hub.metrics_every_s)
            hub.metrics.gpu = hub.gpu
            await hub.metrics.start()
            stack.push_async_callback(hub.metrics.close)
            hub.widgets = Widgets(hub.services)
            # 9. agent tools: the catalog, approvals, grants and calls; calls following a job resume.
            from utils.tools import hub_tools
            from utils.tools.approvals import Approvals
            from utils.tools.grants import Grants
            from utils.tools.calls import Calls
            from utils.tools.catalog import Catalog

            hub.tools = Catalog(hub)
            hub.tools.add_hub_tools(hub_tools.tools())
            hub.services.on_ready.append(hub.tools.refresh_mod)
            hub.approvals = Approvals(hub.db, hub.bus, hub.config)
            hub.grants = Grants(hub.db, hub.bus)
            from utils.prefs import Prefs

            hub.prefs = Prefs(hub)
            hub.calls = Calls(hub, hub.tools, hub.approvals)
            stack.push_async_callback(hub.calls.close)
            await hub.calls.resume()

            async def _backfill() -> None:          # plan 21.5: old cards' edits, once the mods' tools are known
                from utils.tools.records import backfill_edited
                await asyncio.sleep(20)
                try:
                    await backfill_edited(hub)
                except Exception:  # noqa: BLE001
                    log.exception("backfilling approvals.edited")
            backfill = asyncio.create_task(_backfill())
            stack.callback(backfill.cancel)
            # 10. sessions: auto-save, the unclean-shutdown flag, restore at boot (if set).
            from utils.sessions import Sessions

            hub.sessions = Sessions(hub)
            await hub.sessions.start()
            stack.push_async_callback(hub.sessions.close)
            # 11. the mods that are their own repositories: their state and alerts (local git), the daily fetch.
            from utils.repos_watch import RepoWatcher

            hub.repos = RepoWatcher(hub)
            await hub.repos.start()
            stack.push_async_callback(hub.repos.close)
            # 12. setup from the app (capability-enablement 3.1): the same gaifa setup, as one job at a time.
            from utils.setup_jobs import SetupJobs

            hub.setup = SetupJobs(hub, run=hub.options.setup_runner)
            stack.push_async_callback(hub.setup.close)
            log.info("GAIFA %s ready on port %s (root %s)", hub.version, hub.port, paths.root)
            yield

    app = FastAPI(
        title="GAIFA",
        description=("One local hub for every AI service on this machine. Each mod's own API is proxied unchanged at "
                     "`/api/s/{id}/…` (any method); `GET /api/services/{id}/operations` lists it, from the mod's OpenAPI. "
                     "Hub errors are `{detail, code, data?}` with an `X-GAIFA-Error` header."),
        version=hub.version,
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.state.hub = hub
    app.add_middleware(RequestGuard, hub=hub)  # Host and Origin rules: DNS rebinding, cross-site requests
    _error_handlers(app)

    app.include_router(system.router)
    hub.mark_live("system")
    app.include_router(events.router)
    app.include_router(services.router)
    app.include_router(proxy.router)
    app.include_router(models.router)
    app.include_router(metrics.router)  # before outputs: /api/outputs/stats isn't an output id
    app.include_router(outputs.router)
    app.include_router(memory.router)
    app.include_router(gpu.router)
    app.include_router(widgets.router)
    app.include_router(overview.router)
    app.include_router(settings.router)
    app.include_router(tools.router)
    app.include_router(skills.router)
    app.include_router(sessions.router)
    app.include_router(prefs.router)
    app.include_router(mentions.router)  # /api/mentions (48.1)
    app.include_router(mcp.router)  # /mcp: the tools over MCP (13.4)
    app.include_router(webpages.router)  # /api/web/read (30.8)
    app.include_router(repos.router)  # /api/repos (mod-repos 3.3)
    app.include_router(llm.router)  # /api/llm (llm-servers 3.4)
    app.include_router(ui_store.router)  # /api/ui/store (settings-that-stick 4.1)
    app.include_router(notify.router)  # /api/notify (calendar 2.1)
    app.include_router(lan.router)  # /signin, /api/lan (lan-access 1.3)
    app.include_router(setup.router)  # /api/setup (capability-enablement 3.1)
    for area in ("services", "logs", "operations", "proxy", "events", "models", "outputs", "memory", "metrics", "widgets",
                 "overview", "settings", "tools", "sessions", "prefs", "webpages", "gpu", "mentions", "repos", "llm", "ui_store", "notify", "lan", "setup"):
        hub.mark_live(area)

    app.include_router(web.router)
    app.mount("/", WebFiles(directory=paths.web, html=True, check_dir=False), name="web")
    return app


def _service_name(hub: Hub) -> Any:
    """A mod's display name for activity text ("Speech created …"), or its id."""

    def name_of(service_id: str) -> str:
        svc = hub.services.services.get(service_id) if hub.services else None
        return svc.mod.name if svc else service_id

    return name_of


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
    return JSONResponse(body, status_code=status, headers={"X-GAIFA-Error": code})


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

    @app.exception_handler(OutputError)
    async def _output_error(_: Request, e: OutputError) -> JSONResponse:
        return _envelope(e.status, e.code, e.detail, e.data)

    from utils.sessions import SessionError

    @app.exception_handler(SessionError)
    async def _session_error(_: Request, e: SessionError) -> JSONResponse:
        return _envelope(e.status, e.code, e.detail)

    @app.exception_handler(MetricsError)
    async def _metrics_error(_: Request, e: MetricsError) -> JSONResponse:
        return _envelope(422, "invalid_request", str(e))

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

