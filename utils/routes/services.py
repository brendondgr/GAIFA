"""The `services`, `logs` and `operations` areas: `/api/services/...` (brief §6.2)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from utils import operations
from utils.services import ServiceManager

router = APIRouter(tags=["services"])


def _mgr(request: Request) -> ServiceManager:
    return request.app.state.hub.services


@router.get("/api/services/{service_id}/operations", summary="A mod's API as operations (from its OpenAPI)")
async def list_operations(service_id: str, request: Request) -> list[dict[str, Any]]:
    mgr = _mgr(request)
    return await operations.get(mgr, mgr.get(service_id))
