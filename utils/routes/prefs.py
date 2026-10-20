"""The `prefs` area (plan 21.2): `GET/POST /api/prefs`, `PATCH/DELETE /api/prefs/{id}`,
`POST /api/prefs/{id}/approve|reject`. The store is `utils/prefs.py`."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict

router = APIRouter(tags=["prefs"])


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Pref(_M):
    id: str
    scope: Literal["tool", "agent", "thread"]
    tool: str | None = None
    field: str | None = None
    thread: str | None = None
    value: Any
    when: dict[str, Any]
    cue: str
    source: Literal["stated", "inferred", "carried"]
    state: Literal["proposed", "active", "retired", "rejected"]
    confidence: float
    evidence: list[dict[str, Any]]
    seen: int
    contradicted: int
    note: str
    created_ts: float
    updated_ts: float
    last_used_ts: float | None = None


class PrefNew(_M):
    scope: Literal["tool", "agent", "thread"] | None = None
    tool: str | None = None
    field: str | None = None
    thread: str | None = None
    value: Any
    when: dict[str, Any] | None = None
    cue: str | None = None
    source: Literal["stated", "inferred", "carried"] | None = None
    state: Literal["proposed", "active", "retired", "rejected"] | None = None
    confidence: float | None = None
    evidence: list[dict[str, Any]] | None = None
    seen: int | None = None
    note: str | None = None


class PrefPatch(_M):
    value: Any = None
    when: dict[str, Any] | None = None
    cue: str | None = None
    state: Literal["proposed", "active", "retired", "rejected"] | None = None
    confidence: float | None = None
    note: str | None = None
    evidence: list[dict[str, Any]] | None = None
    seen: int | None = None


class Deleted(_M):
    id: str
    deleted: bool


def _p(request: Request) -> Any:
    return request.app.state.hub.prefs


async def _run(coro: Any) -> Any:
    from utils.prefs import PrefError
    from utils.server import HubError

    try:
        return await coro
    except PrefError as e:
        raise HubError(e.status, e.code, e.detail) from None


@router.get("/api/prefs", summary="Preferences; ?state=active|proposed|…, ?tool=, ?scope=tool|agent|thread, ?thread=",
            response_model=list[Pref])
async def list_prefs(request: Request, state: str | None = None, tool: str | None = None, scope: str | None = None,
                     thread: str | None = None) -> list[dict[str, Any]]:
    return await _p(request).list(state, tool, scope, thread)


@router.post("/api/prefs", summary="Save a preference (checked against the tool's schema and choices)", response_model=Pref)
async def create_pref(body: PrefNew, request: Request) -> dict[str, Any]:
    return await _run(_p(request).create(body.model_dump(exclude_none=True)))


@router.patch("/api/prefs/{pid}", summary="Change a preference", response_model=Pref)
async def update_pref(pid: str, body: PrefPatch, request: Request) -> dict[str, Any]:
    return await _run(_p(request).update(pid, body.model_dump(exclude_unset=True)))


@router.delete("/api/prefs/{pid}", summary="Forget a preference", response_model=Deleted)
async def delete_pref(pid: str, request: Request) -> dict[str, Any]:
    await _run(_p(request).delete(pid))
    return {"id": pid, "deleted": True}


@router.post("/api/prefs/{pid}/approve", summary="Approve a proposed preference: it applies from now on", response_model=Pref)
async def approve_pref(pid: str, request: Request) -> dict[str, Any]:
    return await _run(_p(request).decide(pid, True))


@router.post("/api/prefs/{pid}/reject", summary="Reject a proposed preference", response_model=Pref)
async def reject_pref(pid: str, request: Request) -> dict[str, Any]:
    return await _run(_p(request).decide(pid, False))
