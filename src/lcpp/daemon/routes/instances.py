"""Instances: preflight, launch, stop, restart, dismiss, router models, logs.

``{name}`` also accepts a port number, so ``lcpp stop 7071`` and the UI's
names resolve through the same lookup.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, Body, Query, Request, Response
from fastapi.responses import StreamingResponse

from lcpp.daemon.app import state

router = APIRouter(prefix="/api/instances", tags=["instances"])


@router.get("")
async def list_instances(request: Request):
    return await state(request).supervisor.views()


@router.post("/preflight")
async def preflight(request: Request, spec: dict[str, Any] = Body(...)):
    return await asyncio.to_thread(state(request).supervisor.preflight, spec)


@router.post("", status_code=201)
async def launch(request: Request, spec: dict[str, Any] = Body(...)):
    sup = state(request).supervisor
    inst, warnings = await sup.launch(spec)
    return {"instance": await sup.view(inst), "warnings": warnings}


@router.post("/stop-all", status_code=202)
async def stop_all(request: Request):
    return {"stopping": await state(request).supervisor.stop_all()}


@router.get("/{name}")
async def get_instance(request: Request, name: str):
    sup = state(request).supervisor
    return await sup.view(sup.get(name))


@router.delete("/{name}", status_code=202)
async def stop(request: Request, name: str, dismiss: int = 0):
    sup = state(request).supervisor
    if dismiss:
        await sup.dismiss(name)
        return Response(status_code=204)
    return await sup.view(await sup.stop(name))


@router.post("/{name}/restart", status_code=202)
async def restart(request: Request, name: str):
    sup = state(request).supervisor
    return await sup.view(await sup.restart(name))


@router.post("/{name}/models/{model_id}/{action}")
async def router_model(request: Request, name: str, model_id: str, action: str):
    sup = state(request).supervisor
    if action not in ("load", "unload"):
        return Response(status_code=404)
    return await sup.view(await sup.router_action(name, model_id, action))


@router.get("/{name}/logs")
async def logs(request: Request, name: str, lines: int = Query(200, ge=1, le=20000)):
    sup = state(request).supervisor
    return {"lines": await asyncio.to_thread(sup.logs, name, lines)}


@router.get("/{name}/logs/stream")
async def logs_stream(request: Request, name: str):
    """SSE: one ``LogLine`` JSON per event. The journal follower lives exactly
    as long as the client stays connected."""
    follower = state(request).supervisor.follow(name)

    async def events():
        yield ": connected\n\n"
        pending = None
        try:
            while True:
                # Wake at least every 15 s even when the log is quiet, so a
                # closed tab releases its journal follower promptly.
                pending = pending or asyncio.ensure_future(anext(follower))
                done, _ = await asyncio.wait([pending], timeout=15.0)
                if await request.is_disconnected():
                    break
                if not done:
                    yield ": keepalive\n\n"
                    continue
                try:
                    line = pending.result()
                except StopAsyncIteration:
                    break
                pending = None
                yield f"data: {json.dumps(line)}\n\n"
        finally:
            if pending and not pending.done():
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)
            await follower.aclose()

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})
