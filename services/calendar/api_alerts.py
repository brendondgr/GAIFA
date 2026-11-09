"""Routes for fired alerts (calendar plan 2.3): the list, and seen, done (a to-do's), snooze and seen-all.
Each change posts the unread count to the hub (the Calendar item's badge)."""

from __future__ import annotations

import time
from typing import Literal

from fastapi import APIRouter, Body, Query, Request

from api_items import cal
from items import Invalid

router = APIRouter()


def _alerts(request: Request):  # type: ignore[no-untyped-def]
    a = cal(request).alerts
    if a is None:
        raise Invalid("alerts aren't running", "alerts_off")
    return a


@router.get("/v1/alerts", summary="Fired alerts (reminders), unread first, newest first")
def list_alerts(request: Request, state: Literal["unread", "seen", "done", "snoozed", "all"] = "all",
                limit: int = Query(100, ge=1, le=500)) -> dict:
    a = _alerts(request)
    rows = a.list(state, limit)
    return {"alerts": rows, "unread": sum(1 for r in a.list("unread", 500))}


@router.post("/v1/alerts/seen-all", summary="Mark every unread reminder seen")
async def seen_all(request: Request) -> dict:
    return {"seen": await _alerts(request).seen_all()}


@router.post("/v1/alerts/{fid}/seen", summary="Mark a reminder seen")
async def seen(request: Request, fid: str) -> dict:
    return await _alerts(request).mark(fid, "seen")


@router.post("/v1/alerts/{fid}/done", summary="Done: a to-do's reminder also completes the to-do")
async def done(request: Request, fid: str) -> dict:
    return await _alerts(request).mark(fid, "done")


@router.post("/v1/alerts/{fid}/snooze", summary="Snooze a reminder: minutes, or until (unix seconds)")
async def snooze(request: Request, fid: str, minutes: int | None = Query(None, ge=1, le=10080),
                 body: dict | None = Body(None)) -> dict:
    body = body or {}
    until = body.get("until")
    m = minutes or body.get("minutes")
    if until is None:
        until = time.time() + int(m or 10) * 60
    return await _alerts(request).mark(fid, "snoozed", float(until))
