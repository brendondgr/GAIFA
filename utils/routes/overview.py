"""`GET /api/overview`: everything the Overview page shows first, in one call (brief §6.2)."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Request

from utils.api_models import Overview
from utils.routes.system import system_info
from utils.services.status import ACTIVE_JOBS
from utils.services.views import summary

router = APIRouter(tags=["overview"])

RECENT_OUTPUTS = 8
RECENT_ACTIVITY = 30


@router.get("/api/overview", summary="Services, memory, the 8 newest outputs, 30 activity items, alerts, running jobs and system",
            response_model=Overview, response_model_exclude_unset=True)
async def get_overview(request: Request) -> dict[str, Any]:
    hub = request.app.state.hub
    mgr = hub.services
    mem = hub.memory
    outputs, system, memory = await asyncio.gather(
        hub.outputs.list(limit=RECENT_OUTPUTS), system_info(hub),
        asyncio.sleep(0, mem.view()) if mem.snapshot else mem.sample(publish=False))
    return {
        "services": [summary(mgr, s) for s in mgr.list()],
        "memory": memory,
        "recent_outputs": outputs["items"],
        "activity": hub.activity.recent(RECENT_ACTIVITY),
        "alerts": hub.alerts.list(),
        "jobs": [j for s in mgr.list() for j in s.jobs if j["state"] in ACTIVE_JOBS],
        "system": system,
    }
