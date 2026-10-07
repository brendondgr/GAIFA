"""The `sessions` area (plan 15.2): `GET/POST /api/sessions`, `PUT/DELETE /api/sessions/{id}`,
`POST /api/sessions/{id}/restore?dry_run=1`, `GET /api/sessions/state`."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

router = APIRouter(tags=["sessions"])


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Session(_M):
    id: str
    name: str
    auto: bool
    created_ts: float
    updated_ts: float
    summary: str
    snapshot: dict[str, Any]


class SessionStep(_M):
    action: str
    target: str
    detail: str
    bytes: int | None = None
    spec: dict[str, Any] | None = None
    ok: bool | None = None
    error: str | None = None


class SessionMemory(_M):
    available_bytes: int
    freed_bytes: int
    needed_bytes: int
    reserve_bytes: int
    after_bytes: int
    fits: bool


class Restore(_M):
    session: str
    steps: list[SessionStep]
    memory: SessionMemory
    dry_run: bool
    results: list[SessionStep] | None = None
    ok: bool | None = None


class SessionState(_M):
    unclean_shutdown: bool = Field(description="The hub didn't stop cleanly last time (offer to restore the last session)")
    last_auto: Session | None = Field(description='The setup before this start ("Before restart"): what to offer to restore')
    restoring: str | None
    restore_on_boot: bool


class NewSession(_M):
    name: str = Field(min_length=1, max_length=80)


def _s(request: Request) -> Any:
    return request.app.state.hub.sessions


@router.get("/api/sessions", summary="Saved sessions (named setups), the auto-saved one last", response_model=list[Session])
async def list_sessions(request: Request) -> list[dict[str, Any]]:
    return await _s(request).list()


@router.get("/api/sessions/state", summary="Whether the last shutdown was unclean, and the setup from before this start",
            response_model=SessionState)
async def session_state(request: Request) -> dict[str, Any]:
    s = _s(request)
    return {"unclean_shutdown": s.unclean_previous, "last_auto": await s.before_restart(), "restoring": s.restoring,
            "restore_on_boot": request.app.state.hub.config.sessions.restore_on_boot}


@router.post("/api/sessions", status_code=201, summary="Save what runs and what's loaded now under a name (same name: replaced)",
             response_model=Session)
async def save_session(body: NewSession, request: Request) -> dict[str, Any]:
    return await _s(request).save(body.name)


@router.put("/api/sessions/{sid}", summary="Rename a session", response_model=Session)
async def rename_session(sid: str, body: NewSession, request: Request) -> dict[str, Any]:
    return await _s(request).rename(sid, body.name)


@router.delete("/api/sessions/{sid}", status_code=204, summary="Delete a session")
async def delete_session(sid: str, request: Request) -> None:
    await _s(request).delete(sid)


@router.post("/api/sessions/{sid}/restore", summary="Restore a session (dry_run=1: only the steps and the memory plan)",
             response_model=Restore, response_model_exclude_none=True)
async def restore_session(sid: str, request: Request, dry_run: bool = False) -> dict[str, Any]:
    return await _s(request).restore(sid, dry_run)
