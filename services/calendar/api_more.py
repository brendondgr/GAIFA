"""Routes for free time, day plans, `.ics` import and export, and proposals (calendar plan 1.6, 1.7, 4.3)."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Literal

from fastapi import APIRouter, File, Header, Query, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

import free as F
import ics
import timeutil as T
from api_items import ItemIn, cal, origin_of
from items import Invalid

router = APIRouter()


@router.get("/v1/free", summary="Free time between from and to (deterministic): slots of at least `min` minutes")
def free_time(request: Request, from_: str = Query(..., alias="from"), to: str = Query(...),
              min: int = Query(30, ge=5, le=1440, description="The shortest slot, in minutes"),
              within: Literal["work", "any"] = Query("work", description="work: inside working hours; any: any time"),
              include_focus: bool = Query(False, description="May focus blocks be used?")) -> dict:
    c = cal(request)
    frm, t = T.from_query(from_), T.from_query(to)
    if t <= frm or t - frm > timedelta(days=31):
        raise Invalid("the range is from < to, up to 31 days", "bad_range")
    slots = F.free(c.items, c.settings.get(), frm, t, min, within, include_focus)
    return {"slots": slots, "minutes": sum(s["minutes"] for s in slots)}


class PlanIn(BaseModel):
    date: str | None = Field(None, description="The day to plan, YYYY-MM-DD (default today)")
    todo_ids: list[str] | None = Field(None, description="Only these to-dos (default: the open ones due by that day, and undated ones)")


@router.post("/v1/plan", summary="Plan a day: open to-dos placed in free working time, as a proposal you tick and add")
def plan(request: Request, body: PlanIn) -> dict:
    c = cal(request)
    try:
        day = date.fromisoformat(body.date) if body.date else T.now_local().date()
    except ValueError:
        raise Invalid("date is YYYY-MM-DD", "bad_date") from None
    p = F.plan_day(c.items, c.settings.get(), day, body.todo_ids)
    out = c.proposals.create("plan", p["items"], {"kind": "plan", "date": day.isoformat()}, [
        {"title": x["title"], "why": f"no free {x['estimate_min']} minutes left that day"} for x in p["left"]], checked=False)
    return out


@router.post("/v1/import", summary="Read an .ics file into a proposal (nothing is added until you accept it)")
async def import_ics(request: Request, file: UploadFile | None = File(None), x_gaifa_origin: str | None = Header(None)) -> dict:
    c = cal(request)
    if file is not None:
        data = await file.read()
        name = file.filename
    else:
        raw = await request.body()
        try:
            import json
            body = json.loads(raw or b"{}")
            data, name = str(body.get("ics") or "").encode(), body.get("name")
        except ValueError:
            data, name = raw, None
    if not data:
        raise Invalid("send an .ics file (multipart `file`) or {\"ics\": \"BEGIN:VCALENDAR…\"}", "no_file")
    try:
        items, skipped = ics.read(data, c.store)
    except ValueError as e:
        raise Invalid(str(e), "bad_ics") from None
    return c.proposals.create("ics", items, {"kind": "ics", "name": name}, skipped, checked=True)


@router.get("/v1/export.ics", summary="Export calendars as an .ics file")
def export(request: Request, calendars: str | None = None) -> Response:
    c = cal(request)
    items = c.store.items(calendars=calendars.split(",") if calendars else None)
    return Response(ics.write(c.store, items), media_type="text/calendar",
                    headers={"Content-Disposition": 'attachment; filename="gaifa-calendar.ics"'})


@router.get("/v1/items/{iid}.ics", summary="One item as an .ics file")
def export_item(request: Request, iid: str) -> Response:
    c = cal(request)
    return Response(ics.write(c.store, [c.store.get(iid)]), media_type="text/calendar",
                    headers={"Content-Disposition": f'attachment; filename="{iid}.ics"'})


# ---- proposals -----------------------------------------------------------------------------------------------------
class ProposalItem(ItemIn):
    pass


class ProposalIn(BaseModel):
    items: list[ProposalItem] = Field(..., min_length=1, max_length=200,
                                      description="The items, each with a title and `when` (words or ISO) or start/end/due")
    source: dict[str, Any] | None = Field(None, description="Where the dates came from: {kind: document|agent, title?, ref?}")


@router.post("/v1/proposals", summary="Propose items for the user to tick and add (adds nothing by itself)")
def propose(request: Request, body: ProposalIn, x_gaifa_origin: str | None = Header(None)) -> dict:
    c = cal(request)
    o = origin_of(x_gaifa_origin)
    raw = []
    for it in body.items:
        d = it.model_dump(exclude_unset=True)
        if "alerts" in d and d["alerts"] is not None:
            d["alerts"] = [{"before_min": x} for x in d["alerts"]]
        d["source"] = {"kind": (body.source or {}).get("kind") or "agent", **({"thread": o["thread"]} if o.get("thread") else {})}
        raw.append(d)
    return c.proposals.create("items", raw, body.source or {"kind": "agent"})


@router.get("/v1/proposals/{pid}", summary="A proposal and its items")
def get_proposal(request: Request, pid: str) -> dict:
    return cal(request).proposals.get(pid)


class AcceptIn(BaseModel):
    ids: list[str] | None = Field(None, description="The items to add (their `pid`); default all that can be added")
    calendar: str | None = None
    project_id: str | None = None


@router.post("/v1/proposals/{pid}/accept", summary="Add the ticked items (one undo)")
def accept(request: Request, pid: str, body: AcceptIn, x_gaifa_origin: str | None = Header(None)) -> dict:
    return cal(request).proposals.accept(pid, body.ids, body.calendar, body.project_id, origin_of(x_gaifa_origin))
