"""Load and unload a mod's models through its `[memory]` operations (plan 2.7).

The call runs in the background: the route answers 202 with `load: "loading"`,
and the result arrives as a `service` event. A load goes through the memory
manager first (plan 5.4): it answers `409 needs_room` when the load needs room
and `make_room` wasn't asked for (nor `auto_make_room` set); otherwise room is
made and reserved in the background before the mod's load call.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import httpx

from utils.services.model import Service, ServiceError

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


def _set_load(svc: Service, value: str) -> None:
    """The hub's own load state for `svc`, stamped so a status read that started earlier can't undo it."""
    svc.load = value
    svc.load_set_at = time.monotonic()


async def load(mgr: ServiceManager, service_id: str, make_room: bool = False) -> Service:
    svc = mgr.get(service_id)
    method, path = _op(svc, "load")
    _require_up(svc)
    if svc.load in ("loaded", "loading"):
        return svc
    mem = mgr.memory
    if mem is not None:
        await mem.precheck(svc.id, make_room)  # 409 needs_room, with the plan, for the Make-room dialog
    _set_load(svc, "loading")
    mgr._publish(svc)
    mgr._spawn(svc, _load(mgr, svc, svc.gen, method, path, make_room))
    return svc


async def _load(mgr: ServiceManager, svc: Service, gen: int, method: str, path: str, make_room: bool) -> None:
    mem = mgr.memory
    if mem is not None:
        try:
            await mem.ensure_room(svc.id, make_room=make_room)
        except ServiceError as e:
            if gen == svc.gen:
                _set_load(svc, "unloaded")
                mgr._publish(svc)
                await mgr.activity.add(f"Couldn't load {svc.mod.name}: {e.detail}", service=svc.id, level="error")
            return
    try:
        await _call(mgr, svc, gen, method, path, "load")
    finally:
        if mem is not None:
            mem.release(svc.id)


async def unload(mgr: ServiceManager, service_id: str) -> Service:
    svc = mgr.get(service_id)
    method, path = _op(svc, "unload")
    _require_up(svc)
    if svc.load in ("unloaded", "unloading"):
        return svc
    _set_load(svc, "unloading")
    mgr._publish(svc)
    mgr._spawn(svc, _call(mgr, svc, svc.gen, method, path, "unload"))
    return svc


async def unload_now(mgr: ServiceManager, svc: Service, note: str = "") -> bool:
    """Unload and wait for the mod's answer (make-room). True when it unloaded."""
    try:
        method, path = _op(svc, "unload")
    except ServiceError:
        return False
    if not svc.up or svc.load != "loaded":
        return False
    _set_load(svc, "unloading")
    mgr._publish(svc)
    await _call(mgr, svc, svc.gen, method, path, "unload", note)
    return svc.load == "unloaded"


async def _call(mgr: ServiceManager, svc: Service, gen: int, method: str, path: str, which: str, note: str = "") -> None:
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
        _set_load(svc, "loaded" if which == "load" else "unloaded")
        if which == "unload" and mgr.memory is not None:
            mgr.memory.unloaded(svc.id)
        mgr._publish(svc)
        await mgr.activity.add(f"{verb} {svc.mod.name}{note} ({secs:.1f}s)", service=svc.id)
    else:
        _set_load(svc, before)
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
