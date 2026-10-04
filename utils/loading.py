"""Load and unload a mod's models through its `[memory]` operations (plan 2.7).

The call runs in the background: the route answers 202 with `load: "loading"`,
and the result arrives as a `service` event. Phase 5 adds make-room planning
in front of `load` and uses the same calls to free memory.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import httpx

from utils.services import Service, ServiceError

if TYPE_CHECKING:
    from utils.services import ServiceManager

CALL_TIMEOUT = httpx.Timeout(connect=3.0, write=60.0, read=1800.0, pool=10.0)  # loading can take minutes


def _op(svc: Service, which: str) -> tuple[str, str]:
    mem = svc.m.memory if svc.m else None
    op = getattr(mem, which, None) if mem else None
    if not op:
        raise ServiceError(409, "not_unloadable", f"{svc.mod.name} has no [memory] {which} operation in its service.toml")
    method, path = op.split(" ", 1)
    return method, path


def _require_up(svc: Service) -> None:
    if not svc.up:
        raise ServiceError(503, "service_not_running", f"{svc.mod.name} is not running (state: {svc.state})", {"state": svc.state})


async def load(mgr: ServiceManager, service_id: str, make_room: bool = False) -> Service:
    svc = mgr.get(service_id)
    method, path = _op(svc, "load")
    _require_up(svc)
    if svc.load in ("loaded", "loading"):
        return svc
    # make_room: Phase 5 plans and frees memory here; until then a load always proceeds.
    svc.load = "loading"
    mgr._publish(svc)
    mgr._spawn(svc, _call(mgr, svc, svc.gen, method, path, "load"))
    return svc


async def unload(mgr: ServiceManager, service_id: str) -> Service:
    svc = mgr.get(service_id)
    method, path = _op(svc, "unload")
    _require_up(svc)
    if svc.load in ("unloaded", "unloading"):
        return svc
    svc.load = "unloading"
    mgr._publish(svc)
    mgr._spawn(svc, _call(mgr, svc, svc.gen, method, path, "unload"))
    return svc


async def _call(mgr: ServiceManager, svc: Service, gen: int, method: str, path: str, which: str) -> None:
    t0 = time.monotonic()
    before = "unloaded" if which == "load" else "loaded"
    try:
        r = await mgr.proxy_client.request(method, svc.url + path, timeout=CALL_TIMEOUT)
        ok, why = 200 <= r.status_code < 300, _reason(r)
    except httpx.HTTPError as e:
        ok, why = False, type(e).__name__
    if gen != svc.gen:
        return  # the mod was stopped or restarted meanwhile
    secs = time.monotonic() - t0
    verb = "Loaded" if which == "load" else "Unloaded"
    if ok:
        svc.load = "loaded" if which == "load" else "unloaded"
        mgr._publish(svc)
        await mgr.activity.add(f"{verb} {svc.mod.name} ({secs:.1f}s)", service=svc.id)
    else:
        svc.load = before
        mgr._publish(svc)
        await mgr.activity.add(f"{svc.mod.name}: {which} failed ({why})", service=svc.id, level="error", route=f"#/s/{svc.id}/logs")


def _reason(r: httpx.Response) -> str:
    if 200 <= r.status_code < 300:
        return ""
    try:
        body = r.json()
        msg = body.get("detail") or body.get("error") or body.get("message") if isinstance(body, dict) else None
    except ValueError:
        msg = None
    return f"HTTP {r.status_code}" + (f": {msg}" if isinstance(msg, str) else "")
