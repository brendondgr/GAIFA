"""The model catalog: list, edit, validate, delete, defaults, discovery.

Edits write ``data/models.json`` atomically and take effect for the next
launch; running instances keep the command line they started with.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Body, Request, Response

from lcpp.catalog import CatalogError
from lcpp.daemon.app import state

router = APIRouter(prefix="/api/models", tags=["models"])


def _running(request: Request) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for inst in state(request).supervisor.instances.values():
        for mid in ([inst.model_id] if inst.model_id else inst.model_ids):
            out.setdefault(mid, []).append(inst.name)
    return out


@router.get("")
async def list_models(request: Request):
    cat = state(request).catalog
    running = _running(request)

    def build():
        return {"defaults": dict(cat.defaults),
                "models": [cat.view(m, running.get(m.id, [])) for m in cat.models.values()]}

    return await asyncio.to_thread(build)


@router.get("/discovered")
async def discovered(request: Request):
    st = state(request)
    return await asyncio.to_thread(st.catalog.discover, st.settings["scan_dirs"])


@router.post("/validate")
async def validate(request: Request, body: dict[str, Any] = Body(...)):
    return await asyncio.to_thread(state(request).catalog.validate_input, body)


@router.put("/defaults")
async def put_defaults(request: Request, body: dict[str, Any] = Body(...)):
    return await asyncio.to_thread(state(request).catalog.set_defaults, body)


@router.put("/{model_id}")
async def put_model(request: Request, model_id: str, body: dict[str, Any] = Body(...)):
    cat = state(request).catalog
    body = {**body, "id": body.get("id") or model_id}
    if body["id"] != model_id:
        raise CatalogError("renaming a model is not supported; add a new one instead")
    entry = await asyncio.to_thread(cat.entry_from_input, body)
    await asyncio.to_thread(cat.upsert, entry)
    return cat.view(entry, _running(request).get(entry.id, []))


@router.delete("/{model_id}", status_code=204)
async def delete_model(request: Request, model_id: str):
    running = _running(request).get(model_id)
    if running:
        raise CatalogError(f"Model {model_id} is in use by {', '.join(running)}", "model_in_use", 409)
    await asyncio.to_thread(state(request).catalog.delete, model_id)
    return Response(status_code=204)
