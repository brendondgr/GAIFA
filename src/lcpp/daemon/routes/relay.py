"""Relay status and registrations managed by lcpp."""

from __future__ import annotations

from fastapi import APIRouter, Request

from lcpp.daemon.app import state

router = APIRouter(prefix="/api", tags=["relay"])


@router.get("/relay")
async def get_relay(request: Request):
    return await state(request).relay.overview()


@router.post("/relay/test")
async def test_relay(request: Request):
    return await state(request).relay.status(fresh=True)
