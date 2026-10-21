"""The `memory` area: `/api/memory`, `/api/memory/plan` and `/api/memory/acquire` (brief §6.2, architecture §6)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from utils.api_models import Grant, MakeRoomPlan, SystemMemory
from utils.memory.manager import ACQUIRE_TTL_S, MemoryManager
from utils.memory.triggers import HEADER, YES

router = APIRouter(tags=["memory"])


def _mem(request: Request) -> MemoryManager:
    return request.app.state.hub.memory


class PlanRequest(BaseModel):
    service: str
    needs_bytes: int | None = Field(None, ge=0, description="Default: the mod's estimate or learned peak, whichever is larger")


class AcquireRequest(BaseModel):
    service: str
    needs_bytes: int = Field(ge=0)
    reason: str = ""


@router.get("/api/memory", summary="Memory now: system, GPU, each mod, other, reserve", response_model=SystemMemory,
            response_model_exclude_unset=True)
async def get_memory(request: Request) -> dict[str, Any]:
    mem = _mem(request)
    # The last sample's numbers with load states as of now (a load may have finished since).
    return mem.view() if mem.snapshot else await mem.sample(publish=False)


@router.post("/api/memory/plan", summary="What loading a mod would unload (nothing is changed)", response_model=MakeRoomPlan)
async def plan_room(body: PlanRequest, request: Request) -> dict[str, Any]:
    return await _mem(request).fresh_plan(body.service, body.needs_bytes)


@router.post("/api/memory/acquire", summary="A mod asks for memory before it loads something; make_room=1 (or X-AIHub-Make-Room: 1) unloads others if needed", response_model=Grant)
async def acquire(body: AcquireRequest, request: Request, make_room: bool = False) -> dict[str, Any]:
    mem = _mem(request)
    allow = make_room or request.headers.get(HEADER, "").strip().lower() in YES
    plan, freed = await mem.ensure_room(body.service, body.needs_bytes, make_room=allow, ttl=ACQUIRE_TTL_S)
    if mem.activity and freed:
        svc = mem.mgr.get(body.service)
        await mem.activity.add(f"Made room for {svc.mod.name}" + (f" ({body.reason})" if body.reason else ""), service=svc.id)
    return {"granted": True, "freed": freed, "plan": plan}
