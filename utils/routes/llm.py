"""The `llm` area (plan llm-servers 3.4): every local language-model engine, through the `[llm]` contract.

`GET /api/llm/engines` gathers each mod that declares `[llm]` (lcpp, vllm, …): whether it runs, its engine
state and its catalog, each model marked with the relay name it gets once loaded. `POST /api/llm/{id}/load
{id}` and `/unload {id?}` go to that mod; a load that needs memory answers the mod's own `409 needs_room`
(with the hub's plan), and `?make_room=1` lets GAIFA unload idle mods for it.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from utils.services.model import ServiceError

router = APIRouter(tags=["llm"])
RUNNING = ("starting", "ready", "degraded")


class _Model(BaseModel):
    model_config = ConfigDict(extra="allow")


class LlmModel(_Model):
    id: str
    name: str
    format: str | None = None
    size_gb: float | None = None
    memory_gb: float | None = None
    context: int | None = None
    downloaded: bool | None = None
    loaded: bool = False
    relay_model: str | None = Field(None, description="The relay's name for it once loaded (what a chat picks)")


class LlmEngine(_Model):
    id: str = Field(description="The mod")
    name: str
    state: str = Field(description="The mod's state (ready, stopped, …)")
    running: bool
    engine: dict[str, Any] | None = Field(description="The mod's engine: {state, loaded}; null while the mod is stopped")
    models: list[LlmModel]
    error: str | None = None


class LlmAction(_Model):
    """The engine's answer to a load or unload, passed on (fields beyond these are the mod's own)."""
    id: str | None = None
    state: str | None = None
    loaded: list[str] | None = None


class LoadBody(BaseModel):
    id: str | None = None


def _engines(request: Request) -> list[Any]:
    mgr = request.app.state.hub.services
    return [s for s in mgr.list() if s.m is not None and s.m.llm is not None]


async def _call(request: Request, svc: Any, op: str, body: dict | None = None, headers: dict | None = None) -> httpx.Response:
    method, path = op.split(" ", 1)
    mgr = request.app.state.hub.services
    return await mgr.client.request(method, svc.url + path, json=body, headers=headers, timeout=60)


async def _one(request: Request, svc: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"id": svc.id, "name": svc.mod.name or svc.id, "state": svc.state,
                           "running": svc.state in RUNNING, "engine": None, "models": [], "error": None}
    if not out["running"]:
        return out
    llm = svc.m.llm
    try:
        cat = await _call(request, svc, llm.catalog)
        out["models"] = (cat.json() or {}).get("models") or [] if cat.status_code < 400 else []
        if cat.status_code >= 400:
            out["error"] = f"catalog: HTTP {cat.status_code}"
        if llm.engine:
            eng = await _call(request, svc, llm.engine)
            out["engine"] = eng.json() if eng.status_code < 400 else None
    except (httpx.HTTPError, ValueError) as e:
        out["error"] = f"{type(e).__name__}: {e}"[:200]
    return out


@router.get("/api/llm/engines", summary="Every local LLM engine ([llm] mods): its state, engine and catalog",
            response_model=list[LlmEngine])
async def engines(request: Request) -> list[dict[str, Any]]:
    return list(await asyncio.gather(*(_one(request, s) for s in _engines(request))))


def _engine(request: Request, sid: str) -> Any:
    svc = next((s for s in _engines(request) if s.id == sid), None)
    if svc is None:
        raise ServiceError(404, "engine_not_found", f"{sid} isn't a mod with [llm] (a local LLM engine)")
    if svc.state not in RUNNING:
        raise ServiceError(409, "engine_stopped", f"{svc.mod.name or sid} isn't running; start it first", {"service": sid})
    return svc


async def _relay(request: Request, svc: Any, op: str | None, body: dict, make_room: bool) -> Any:
    if not op:
        raise ServiceError(405, "not_supported", f"{svc.id} declares no such [llm] operation")
    try:
        r = await _call(request, svc, op, body, {"X-GAIFA-Make-Room": "1"} if make_room else None)
    except httpx.HTTPError as e:
        raise ServiceError(502, "engine_unreachable", f"{svc.id}: {type(e).__name__}") from e
    try:
        data = r.json()
    except ValueError:
        data = {"detail": r.text[:300]}
    if r.status_code >= 400:     # the mod's own answer (needs_room carries the hub's plan): passed on as it is
        return JSONResponse(data if isinstance(data, dict) else {"detail": str(data)}, status_code=r.status_code,
                            headers={"X-GAIFA-Error": (data or {}).get("code", "engine_error") if isinstance(data, dict) else "engine_error"})
    return data


@router.post("/api/llm/{sid}/load", status_code=202, response_model=LlmAction, response_model_exclude_none=True,
             summary="Start one of an engine's models ({id}); 409 needs_room when memory is short (make_room=1 lets "
                     "GAIFA unload idle mods)")
async def load(sid: str, body: LoadBody, request: Request, make_room: bool = False) -> Any:
    svc = _engine(request, sid)
    if not body.id:
        raise ServiceError(422, "invalid_param", "id: which model to load")
    return await _relay(request, svc, svc.m.llm.load, {"id": body.id}, make_room)


@router.post("/api/llm/{sid}/unload", response_model=LlmAction, response_model_exclude_none=True, summary="Stop one of an engine's models ({id}), or all of them")
async def unload(sid: str, request: Request, body: LoadBody | None = None) -> Any:
    svc = _engine(request, sid)
    return await _relay(request, svc, svc.m.llm.unload, {"id": body.id} if body and body.id else {}, False)
