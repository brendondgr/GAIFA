"""Hugging Face GGUF downloads: resolve a repo or link, then download into
``models/<dir>/`` and add the result to the catalog."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Request, Response

from lcpp.daemon.app import state

router = APIRouter(prefix="/api/downloads", tags=["downloads"])


@router.get("")
async def list_downloads(request: Request):
    return state(request).downloads.list()


@router.post("/resolve")
async def resolve(request: Request, body: dict[str, Any] = Body(...)):
    return await state(request).downloads.resolve(str(body.get("input") or ""))


@router.post("", status_code=201)
async def start(request: Request, body: dict[str, Any] = Body(...)):
    return await state(request).downloads.start(body)


@router.post("/{job_id}/cancel")
async def cancel(request: Request, job_id: str):
    return await state(request).downloads.cancel(job_id)


@router.post("/{job_id}/retry")
async def retry(request: Request, job_id: str):
    return await state(request).downloads.retry(job_id)


@router.delete("/{job_id}", status_code=204)
async def dismiss(request: Request, job_id: str):
    await state(request).downloads.dismiss(job_id)
    return Response(status_code=204)
