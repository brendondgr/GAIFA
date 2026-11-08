"""The `ui_store` area: `GET/PATCH /api/ui/store/{scope}` (plan settings-that-stick 4.1), what a page remembers."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from utils.services import ServiceError
from utils.ui_store import StoreError, UiStore

router = APIRouter(tags=["ui"])


class StoreValues(BaseModel):
    values: dict[str, Any] = Field(description="Key → the JSON value a page saved")


class StorePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    set: dict[str, Any] = Field({}, description="Keys to set (each value ≤ 16 KB)")
    delete: list[str] = Field([], description="Keys to remove")


def _store(request: Request) -> UiStore:
    hub = request.app.state.hub
    if getattr(hub, "ui_store", None) is None:
        hub.ui_store = UiStore(hub.paths.state / "ui")
    return hub.ui_store


def _scope(request: Request, scope: str) -> str:
    mgr = request.app.state.hub.services
    if scope != "hub" and (mgr is None or scope not in {s.id for s in mgr.list()}):
        raise ServiceError(404, "not_found", f"No mod {scope!r}")
    return scope


@router.get("/api/ui/store/{scope}", summary="What a page remembers: a mod id, or `hub` for the hub's own pages", response_model=StoreValues)
async def get_store(scope: str, request: Request) -> dict[str, Any]:
    return {"values": _store(request).get(_scope(request, scope))}


@router.patch("/api/ui/store/{scope}", summary="Set and delete keys; the others stay as they are", response_model=StoreValues)
async def patch_store(scope: str, body: StorePatch, request: Request) -> dict[str, Any]:
    try:
        values, changed = _store(request).change(_scope(request, scope), body.set, body.delete)
    except StoreError as e:
        raise ServiceError(e.status, "payload_too_large" if e.status == 413 else "invalid_value", str(e)) from None
    if changed:
        request.app.state.hub.bus.publish({"type": "ui_store", "scope": scope, "keys": changed})
    return {"values": values}
