"""The `models` area: `/api/models/...` (brief §6.2), backed by `utils/registry/`."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Request, Response

from utils.api_models import Model, ModelList, ScanResult
from utils.registry import Patch, Registry
from utils.registry import adding
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


@router.post("/api/models/scan", summary="Model files in data/models that aren't registered yet, grouped into models", response_model=ScanResult, response_model_exclude_unset=True)
async def scan_models(request: Request) -> dict[str, Any]:
    reg = _reg(request)
    return {"discovered": await asyncio.to_thread(adding.discovered, reg)}


@router.post("/api/models", status_code=201, summary="Register a model (a file or folder in data/models)", response_model=Model, response_model_exclude_unset=True)
async def add_model(body: adding.ModelInput, request: Request) -> dict[str, Any]:
    return await adding.add(_reg(request), body)


@router.get("/api/models/{model_id}", summary="One model, with its files and status", response_model=Model, response_model_exclude_unset=True)
async def get_model(model_id: str, request: Request) -> dict[str, Any]:
    return _reg(request).view(model_id)


@router.put("/api/models/{model_id}", summary="Edit a model's name, kind, services, source, tags or notes", response_model=Model, response_model_exclude_unset=True)
async def save_model(model_id: str, patch: Patch, request: Request) -> dict[str, Any]:
    return await _reg(request).update(model_id, patch)


@router.post("/api/models/{model_id}/verify", status_code=202, summary="Hash a model's files in the background (reset=1 records new checksums)", response_model=Model, response_model_exclude_unset=True)
async def verify_model(model_id: str, request: Request, reset: bool = False) -> dict[str, Any]:
    return _reg(request).verifier.request(model_id, reset=reset)


@router.delete("/api/models/{model_id}", status_code=204, summary="Remove a model from the registry (files=1 also deletes its files)")
async def delete_model(model_id: str, request: Request, files: bool = False) -> Response:
    await _reg(request).delete(model_id, files=files)
    return Response(status_code=204)
