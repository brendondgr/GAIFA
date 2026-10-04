"""`GET /api/events`: the hub's server-sent event stream."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from utils.events import sse_stream

router = APIRouter(tags=["events"])


@router.get("/api/events", summary="Server-sent HubEvents")
async def events(request: Request) -> StreamingResponse:
    hub = request.app.state.hub
    return StreamingResponse(
        sse_stream(hub.bus, hub.sse_ping_s),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
