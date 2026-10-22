"""The `gpu` area (plan 31.1): `/api/gpu`, acquire, renew, release and cancel a GPU lease (utils/gpu.py)."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from utils.gpu import WAIT_MAX_S, GpuError, GpuQueue
from utils.services.model import ServiceError

router = APIRouter(tags=["gpu"])

LeaseClass = Literal["interactive", "job", "background"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class GpuAhead(_Model):
    id: str
    service: str
    label: str
    state: Literal["held", "waiting"]
    eta_s: float | None = Field(description="Its remaining (held) or estimated (waiting) seconds; null when unknown")


class GpuLease(_Model):
    id: str
    service: str
    name: str = Field(description="The mod's display name")
    group: str
    cls: LeaseClass = Field(alias="class")
    label: str
    state: Literal["waiting", "held", "released", "expired", "cancelled"]
    created_ts: float
    renewed_ts: float
    est_s: float | None = None
    thread: str | None = None
    call_id: str | None = None
    parent: str | None = None
    granted_ts: float | None = None
    ended_ts: float | None = None
    elapsed_s: float | None = Field(None, description="Held: seconds since it was granted")
    eta_s: float | None = Field(None, description="Held: seconds left (estimate); waiting: seconds until it starts")
    waited_s: float | None = None
    ahead: list[GpuAhead] | None = Field(None, description="Waiting: what runs before it, in order")
    wait_s: float | None = Field(None, description="Finished: how long it waited")
    run_s: float | None = Field(None, description="Finished: how long it held the slot")


class GpuHolder(_Model):
    group: str | None
    leases: list[GpuLease]


class GpuState(_Model):
    queue: bool = Field(description="config.toml [gpu] queue; false = every lease is granted at once")
    lease_ttl_s: float
    holder: GpuHolder | None
    waiting: list[GpuLease]
    recent: list[GpuLease] = Field(description="The last 20 finished leases, newest first")


class GpuGrant(_Model):
    lease: str
    state: Literal["granted", "waiting", "released", "expired", "cancelled", "unknown"]
    ahead: list[GpuAhead] = []
    eta_s: float | None = None


class AcquireBody(_Model):
    service: str
    group: str | None = Field(None, description="Leases of one group share the slot (default: the mod id)")
    cls: LeaseClass = Field("job", alias="class")
    label: str = ""
    est_s: float | None = Field(None, ge=0)
    parent: str | None = Field(None, description="A held lease this work runs under (X-AIHub-GPU-Lease)")
    thread: str | None = None
    call_id: str | None = None
    lease: str | None = Field(None, description="Repeat the waiting lease's id to keep its place")


class RenewBody(_Model):
    """Only needed to re-register a lease the hub doesn't know (it restarted)."""
    service: str | None = None
    group: str | None = None
    cls: LeaseClass | None = Field(None, alias="class")
    label: str | None = None
    est_s: float | None = None
    parent: str | None = None
    thread: str | None = None
    call_id: str | None = None


def _q(request: Request) -> GpuQueue:
    return request.app.state.hub.gpu


def _error(e: GpuError) -> ServiceError:
    return ServiceError(e.status, e.code, e.detail)


def _answer(q: GpuQueue, lease: Any) -> JSONResponse:
    if lease.state == "held":
        return JSONResponse({"lease": lease.id, "state": "granted"})
    if lease.state == "waiting":
        ahead = q.ahead_of(lease)
        return JSONResponse({"lease": lease.id, "state": "waiting", "ahead": ahead, "eta_s": q.eta(ahead)}, status_code=202)
    return JSONResponse({"lease": lease.id, "state": lease.state})


@router.get("/api/gpu", summary="The GPU slot: what holds it, what waits (in order) and the last 20 leases",
            response_model=GpuState, response_model_exclude_unset=True, response_model_by_alias=True)
async def get_gpu(request: Request) -> dict[str, Any]:
    return _q(request).view()


@router.post("/api/gpu/acquire", summary="A mod asks for the GPU slot before its GPU work: 200 granted, or 202 waiting "
             "(repeat with `lease` to keep its place)", response_model=GpuGrant,
             responses={202: {"model": GpuGrant, "description": "Still waiting"}})
async def acquire(body: AcquireBody, request: Request,
                  wait: float = Query(0, ge=0, le=WAIT_MAX_S, description="Seconds to wait for the grant")) -> Any:
    q = _q(request)
    try:
        lease = await q.acquire(wait, service=body.service, cls=body.cls, label=body.label, group=body.group,
                                est_s=body.est_s, parent=body.parent, thread=body.thread, call_id=body.call_id,
                                lease_id=body.lease)
    except GpuError as e:
        raise _error(e) from None
    if lease.state == "held":
        await q.granted(lease)              # a trigger's room, made now that the work can start (memory/triggers.py)
    return _answer(q, lease)


@router.post("/api/gpu/{lease}/renew", summary="Keep a GPU lease alive (every 10 s); an unknown lease is re-registered "
             "from the body", response_model=GpuGrant, responses={202: {"model": GpuGrant, "description": "Re-registered, waiting"}})
async def renew(lease: str, request: Request, body: RenewBody | None = None) -> Any:
    q = _q(request)
    info = body.model_dump(by_alias=True, exclude_none=True) if body else None
    try:
        got = q.renew(lease, info)
    except GpuError as e:
        raise _error(e) from None
    return _answer(q, got)


@router.post("/api/gpu/{lease}/release", summary="Give the GPU slot back (the work ended, failed or was cancelled)",
             response_model=GpuGrant)
async def release(lease: str, request: Request) -> dict[str, Any]:
    got = _q(request).release(lease)
    return {"lease": lease, "state": got.state if got else "unknown"}


@router.delete("/api/gpu/{lease}", summary="Cancel a waiting GPU lease (the queue's Cancel); a held one is a 409",
               response_model=GpuGrant)
async def cancel(lease: str, request: Request) -> dict[str, Any]:
    try:
        got = _q(request).cancel(lease)
    except GpuError as e:
        raise _error(e) from None
    return {"lease": lease, "state": got.state}
