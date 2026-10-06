"""Routes for AIHub (architecture §4.6): the status AIHub polls."""

from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/v1/status", summary="Load state, queue and stats for AIHub")
def status(request: Request) -> dict:
    return {"loaded": False, "busy": False, "idle_s": None, "stats": [], "jobs": []}
