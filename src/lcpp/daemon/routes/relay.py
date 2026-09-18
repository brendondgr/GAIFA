"""Relay status, publishing instances, and lcpp's registrations on the relay."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Request, Response

from lcpp.daemon.app import state

router = APIRouter(prefix="/api", tags=["relay"])


@router.get("/relay")
async def get_relay(request: Request):
    return await state(request).relay.overview()


@router.post("/relay/test")
async def test_relay(request: Request):
    return await state(request).relay.status(fresh=True)


@router.delete("/relay/registrations/{key}", status_code=204)
async def remove_registration(request: Request, key: str):
    await state(request).relay.remove_registration(key)
    return Response(status_code=204)


@router.post("/relay/cleanup")
async def cleanup(request: Request):
    return {"removed": await state(request).relay.cleanup_orphans()}


@router.post("/instances/{name}/relay")
async def publish(request: Request, name: str, body: dict[str, Any] = Body(default_factory=dict)):
    st = state(request)
    inst = await st.relay.publish(name, body.get("alias"))
    return await st.supervisor.view(inst)


@router.delete("/instances/{name}/relay")
async def unpublish(request: Request, name: str):
    st = state(request)
    inst = await st.relay.unpublish(name)
    return await st.supervisor.view(inst)
