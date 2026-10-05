"""`GET /api/events`: the hub's server-sent event stream, and `GET /api/events/recent`:
what the stream would have told a client that just connected (activity, alerts, running jobs)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from utils.api_models import RecentEvents
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


@router.get("/api/events/recent", summary="Recent activity, current alerts and running jobs", response_model=RecentEvents, response_model_exclude_unset=True)
async def recent(request: Request, limit: int = Query(80, ge=1, le=500)) -> dict[str, Any]:
    """Until `/api/overview` exists (Phase 6), the UI fills its overview's activity, alerts and jobs from this."""
    hub = request.app.state.hub
    jobs = [j for s in (hub.services.list() if hub.services else []) for j in s.jobs if j["state"] in ("queued", "running")]
    return {"activity": hub.activity.recent(limit), "alerts": hub.alerts.list(), "jobs": jobs}
