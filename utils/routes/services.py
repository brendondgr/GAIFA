"""The `services`, `logs` and `operations` areas: `/api/services/...` (brief §6.2).

start, stop and restart answer 202 at once with the new state; add `?wait=1`
to wait until the mod is ready, failed or stopped (the CLI does).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from utils import config as config_mod
from utils import operations
from utils.services import check, loading
from utils.api_models import CheckReport, Logs, Operation, Rescan, SavedConfig, ServiceConfigPatch, ServiceDetail, ServiceSummary
from utils.events import SSE_RETRY_MS
from utils.manifest import check_effective_ports, effective
from utils.services.views import detail, summary
from utils.services import ServiceError, ServiceManager

router = APIRouter(tags=["services"])
LOG_LINES_MAX = 5000
RESTART_KEYS = {"port", "env"}


def _mgr(request: Request) -> ServiceManager:
    return request.app.state.hub.services


@router.get("/api/services", summary="Every mod, in sidebar order", response_model=list[ServiceSummary], response_model_exclude_unset=True)
async def list_services(request: Request) -> list[dict[str, Any]]:
    mgr = _mgr(request)
    return [summary(mgr, s) for s in mgr.list()]


@router.post("/api/services/rescan", summary="Pick up added, removed and edited mod folders (no hub restart)", response_model=Rescan)
async def rescan_services(request: Request) -> dict[str, list[str]]:
    return await _mgr(request).rescan(autostart=request.app.state.hub.options.autostart)


@router.get("/api/services/{service_id}", summary="One mod in detail", response_model=ServiceDetail, response_model_exclude_unset=True)
async def get_service(service_id: str, request: Request) -> dict[str, Any]:
    mgr = _mgr(request)
    return detail(mgr, mgr.get(service_id))


async def _act(request: Request, service_id: str, action: str, wait: bool) -> dict[str, Any]:
    mgr = _mgr(request)
    svc = await getattr(mgr, action)(service_id, wait=wait)
    return summary(mgr, svc)


@router.post("/api/services/{service_id}/start", status_code=202, summary="Start a mod", response_model=ServiceSummary, response_model_exclude_unset=True)
async def start_service(service_id: str, request: Request, wait: bool = False) -> dict[str, Any]:
    return await _act(request, service_id, "start", wait)


@router.post("/api/services/{service_id}/stop", status_code=202, summary="Stop a mod", response_model=ServiceSummary, response_model_exclude_unset=True)
async def stop_service(service_id: str, request: Request, wait: bool = False) -> dict[str, Any]:
    return await _act(request, service_id, "stop", wait)


@router.post("/api/services/{service_id}/restart", status_code=202, summary="Stop, then start a mod", response_model=ServiceSummary, response_model_exclude_unset=True)
async def restart_service(service_id: str, request: Request, wait: bool = False) -> dict[str, Any]:
    return await _act(request, service_id, "restart", wait)


@router.post("/api/services/{service_id}/load", status_code=202, summary="Load a mod's models ([memory] load)", response_model=ServiceSummary, response_model_exclude_unset=True)
async def load_service(service_id: str, request: Request, make_room: bool = False) -> dict[str, Any]:
    mgr = _mgr(request)
    return summary(mgr, await loading.load(mgr, service_id, make_room))


@router.post("/api/services/{service_id}/unload", status_code=202, summary="Unload a mod's models ([memory] unload)", response_model=ServiceSummary, response_model_exclude_unset=True)
async def unload_service(service_id: str, request: Request) -> dict[str, Any]:
    mgr = _mgr(request)
    return summary(mgr, await loading.unload(mgr, service_id))


@router.get("/api/services/{service_id}/logs", summary="The last N log lines", response_model=Logs)
async def service_logs(service_id: str, request: Request, lines: int = Query(200, ge=1, le=LOG_LINES_MAX)) -> dict[str, Any]:
    return {"lines": await _mgr(request).logs(service_id, lines)}


@router.get("/api/services/{service_id}/logs/stream", summary="New log lines as server-sent events (each data: is a LogLine)", response_class=StreamingResponse,
            responses={200: {"content": {"text/event-stream": {}}, "description": "Server-sent events; each `data:` is a LogLine"}})
async def stream_logs(service_id: str, request: Request) -> StreamingResponse:
    mgr = _mgr(request)
    svc = mgr.get(service_id)
    hub = request.app.state.hub
    return StreamingResponse(
        _log_events(mgr, svc.id, svc.external, hub.bus.closing, hub.sse_ping_s),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _log_events(mgr: ServiceManager, service_id: str, external: bool, closing: asyncio.Event, ping_s: float) -> AsyncIterator[str]:
    yield f"retry: {SSE_RETRY_MS}\n\n"
    if external:  # nothing to follow; keep the stream open (pings) so the UI shows "no lines"
        follow = None
    else:
        follow = mgr.backend.follow(service_id).__aiter__()
    closed = asyncio.ensure_future(closing.wait())
    nxt: asyncio.Future[Any] | None = None
    try:
        while True:
            if follow is not None and nxt is None:
                nxt = asyncio.ensure_future(follow.__anext__())
            waiting = [closed] + ([nxt] if nxt is not None else [])
            done, _ = await asyncio.wait(waiting, timeout=ping_s, return_when=asyncio.FIRST_COMPLETED)
            if closed in done:
                return
            if nxt is not None and nxt in done:
                try:
                    line = nxt.result()
                except StopAsyncIteration:
                    return
                nxt = None
                yield f"data: {json.dumps(line, separators=(',', ':'))}\n\n"
            elif not done:
                yield ": ping\n\n"
    finally:
        closed.cancel()
        if nxt is not None:
            nxt.cancel()
            await asyncio.gather(nxt, return_exceptions=True)  # let the pending read finish cancelling
        if follow is not None:
            await follow.aclose()


@router.get("/api/services/{service_id}/operations", summary="A mod's API as operations (from its OpenAPI)", response_model=list[Operation], response_model_exclude_unset=True)
async def list_operations(service_id: str, request: Request) -> list[dict[str, Any]]:
    mgr = _mgr(request)
    return await operations.get(mgr, mgr.get(service_id))


@router.get("/api/services/{service_id}/check", summary="Self-test a mod: manifest, command, health, OpenAPI, status, widgets, page", response_model=CheckReport)
async def check_service(service_id: str, request: Request, start: bool = False) -> dict[str, Any]:
    mgr = _mgr(request)
    return await check.run(mgr, mgr.get(service_id), start=start)


@router.put("/api/services/{service_id}/config", summary="Save a mod's [services.<id>] settings in config.toml", response_model=SavedConfig)
async def save_service_config(service_id: str, patch: ServiceConfigPatch, request: Request) -> dict[str, Any]:
    hub = request.app.state.hub
    mgr = _mgr(request)
    svc = mgr.get(service_id)
    sent = patch.model_dump(exclude_unset=True)
    old = svc.eff.as_dict()
    # Only real overrides are written: a value equal to the mod's own default removes its key,
    # so saving the whole form doesn't pin every default into config.toml.
    defaults = effective(svc.mod, _without(hub.config, service_id)).as_dict()
    changes: dict[str, Any] = {}
    for key, value in sent.items():
        if key == "idle_unload_s" and value in (None, 0):
            # "never": written as 0 over a mod's own default (TOML has no null); no key when that's the default
            changes[key] = sent[key] = 0 if defaults[key] is not None else None
        elif value == defaults[key] or value is None:
            changes[key] = None  # back to the default (idle_unload_s: null = never, the default)
            sent[key] = None
        elif key == "env":
            changes["env"] = config_mod.Replace(value)
        else:
            changes[key] = value
    # Check port clashes against the other mods before writing anything.
    try:
        trial = config_mod.validate(_with_service(hub.config, service_id, sent))
    except config_mod.ConfigError as e:
        raise ServiceError(422, "invalid_config", str(e)) from None
    clash = check_effective_ports([s.mod for s in mgr.list()], trial, hub.port).get(service_id)
    if clash:
        raise ServiceError(422, "invalid_config", f"{service_id}: {clash}")
    try:
        cfg = config_mod.save(hub.paths.config_file, {"services": {service_id: changes}})
    except config_mod.ConfigError as e:
        raise ServiceError(422, "invalid_config", str(e)) from None
    hub.config = cfg
    mgr.reconfigure(cfg)
    new = effective(svc.mod, cfg).as_dict()
    keys = RESTART_KEYS | ({"idle_unload_s"} if svc.has_memory else set())  # passed in the env (plan 5.6)
    restart_required = svc.state not in ("stopped", "failed") and any(old[k] != new[k] for k in keys)
    if old["enabled"] and not new["enabled"] and svc.state not in ("stopped",) and not svc.external:
        await mgr.stop(service_id)  # disabling applies now
    await mgr.activity.add(f"Saved settings for {svc.mod.name}" + (" (restart to apply)" if restart_required else ""), service=service_id)
    return {"config": new, "restart_required": restart_required}


def _with_service(cfg: config_mod.Config, service_id: str, sent: dict[str, Any]) -> dict[str, Any]:
    """The config as a dict with this mod's override replaced by `sent` (for validation only)."""
    data = cfg.model_dump(exclude_unset=True)
    services = data.setdefault("services", {})
    overrides = services.pop("overrides", {}) if isinstance(services, dict) else {}
    current = dict(overrides.get(service_id, {}))
    for key, value in sent.items():
        if value is None:
            current.pop(key, None)
        else:
            current[key] = value
    overrides[service_id] = current
    services.update(overrides)
    return data


def _without(cfg: config_mod.Config, service_id: str) -> config_mod.Config:
    """The config with no `[services.<id>]` override: the mod's defaults."""
    return cfg.model_copy(update={"services": cfg.services.model_copy(update={"overrides": {k: v for k, v in cfg.services.overrides.items() if k != service_id}})})
