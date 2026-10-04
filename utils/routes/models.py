"""The `models` area: `/api/models/...` (brief §6.2), backed by `utils/registry/`."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request, Response

from utils.api_models import Model, ModelList
from utils.registry import Patch, Registry
from utils.registry.model import KINDS, STATUSES, RegistryError

router = APIRouter(tags=["models"])


def _reg(request: Request) -> Registry:
    return request.app.state.hub.registry


@router.get("/api/models", summary="Every registered model, with totals by kind and disk space", response_model=ModelList, response_model_exclude_unset=True)
async def list_models(request: Request, kind: str | None = None, service: str | None = None, status: str | None = None, q: str | None = None) -> dict[str, Any]:
    for k in (kind or "").split(","):
        if k and k not in KINDS:
            raise RegistryError(422, "invalid_request", f"kind: {k!r} is not one of {', '.join(KINDS)}")
    if status and status not in STATUSES:
        raise RegistryError(422, "invalid_request", f"status: {status!r} is not one of {', '.join(STATUSES)}")
    return _reg(request).list(kind=kind, service=service, status=status, q=q)


@router.get("/api/models/{model_id}", summary="One model, with its files and status", response_model=Model, response_model_exclude_unset=True)
async def get_model(model_id: str, request: Request) -> dict[str, Any]:
    return _reg(request).view(model_id)


@router.put("/api/models/{model_id}", summary="Edit a model's name, kind, services, source, tags or notes", response_model=Model, response_model_exclude_unset=True)
async def save_model(model_id: str, patch: Patch, request: Request) -> dict[str, Any]:
    return await _reg(request).update(model_id, patch)


@router.delete("/api/models/{model_id}", status_code=204, summary="Remove a model from the registry (files=1 also deletes its files)")
async def delete_model(model_id: str, request: Request, files: bool = False) -> Response:
    await _reg(request).delete(model_id, files=files)
    return Response(status_code=204)
