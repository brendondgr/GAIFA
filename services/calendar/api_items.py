"""Routes for calendars, items, the range, search, the trash, undo, plain-words dates and settings (calendar plan 1.4–1.6).

Writes answer `{item, undo}`; `undo` is a hub path the chat's Undo this turn calls (chat-turn.js `undoOf`).
Who wrote is read from `X-GAIFA-Origin` (a tool call from a chat is the agent's)."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any, Literal

from fastapi import APIRouter, Body, Header, Query, Request
from pydantic import BaseModel, Field

import repeat as R
import timeutil as T
import when as W
from items import Invalid

router = APIRouter()
Scope = Literal["this", "following", "all"]


def origin_of(header: str | None) -> dict[str, Any]:
    if not header:
        return {}
    try:
        v = json.loads(header)
    except ValueError:
        return {}
    return v if isinstance(v, dict) else {}


def cal(request: Request) -> Any:
    return request.app.state.cal


class ItemIn(BaseModel):
    kind: Literal["event", "todo"] | None = Field(None, description="event (default) or todo; a to-do with a time is a reminder")
    title: str | None = Field(None, description="What it is, 1–200 characters")
    when: str | None = Field(None, description="The date and time in words or ISO: 'Fri 1pm for 90 min', 'tomorrow at 10', "
                                               "'Nov 14 all day', '2026-11-14T13:00'. Read by the calendar's own parser; "
                                               "the answer says what it assumed")
    start: str | None = Field(None, description="An event's start: YYYY-MM-DDTHH:MM, or YYYY-MM-DD for all day")
    end: str | None = Field(None, description="An event's end (default: 1 hour later; all day: the next day, exclusive)")
    due: str | None = Field(None, description="A to-do's due date (YYYY-MM-DD) or time (YYYY-MM-DDTHH:MM)")
    repeat: str | None = Field(None, description="How it repeats, in words: 'every Tuesday', 'every weekday', 'monthly on the 1st'")
    rrule: str | None = Field(None, description="Or an RFC 5545 rule: FREQ=WEEKLY;BYDAY=TU")
    alerts: list[int] | None = Field(None, description="Alerts, in minutes before (to-dos: before the due time; an all-day item's are whole days before, at the all-day alert time, 0 on the day), up to 8, each 0–40320 (4 weeks): 1 day before is 1440, 2 days 2880")
    calendar: str | None = Field(None, description="The calendar's name or id (default: the default calendar)")
    project_id: str | None = Field(None, description="The agent's project (p_…) it belongs to")
    notes: str | None = None
    location: str | None = None
    url: str | None = None
    priority: int | None = Field(None, description="To-dos: 0 none, 1 low, 2 medium, 3 high")
    estimate_min: int | None = Field(None, description="To-dos: how long it takes, in minutes (for planning a day)")
    busy: Literal["busy", "free", "focus"] | None = Field(None, description="Events: free doesn't block free time; focus is a focus block")
    prep: dict | None = Field(None, description="The page's own: {task_id, before_min} of the event's prep task (calendar 6.3)")


def _body(m: BaseModel) -> dict[str, Any]:
    d = m.model_dump(exclude_unset=True)
    if "alerts" in d and d["alerts"] is not None:
        d["alerts"] = [{"before_min": x} for x in d["alerts"]]
    return d


# ---- calendars ---------------------------------------------------------------------------------------------------
class CalendarIn(BaseModel):
    name: str | None = None
    color: str | None = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$")
    hidden: bool | None = None
    is_default: bool | None = None
    position: int | None = None


@router.get("/v1/calendars", summary="The calendars")
def calendars(request: Request) -> list[dict]:
    return cal(request).store.calendars()


@router.post("/v1/calendars", summary="Add a calendar")
def add_calendar(request: Request, body: CalendarIn) -> dict:
    if not (body.name or "").strip():
        raise Invalid("a calendar needs a name")
    c = cal(request).store.add_calendar(body.name or "", body.color, bool(body.is_default))
    return c if body.hidden is None else cal(request).store.patch_calendar(c["id"], {"hidden": body.hidden})


@router.patch("/v1/calendars/{cid}", summary="Rename, recolour, hide or make default")
def patch_calendar(request: Request, cid: str, body: CalendarIn) -> dict:
    return cal(request).store.patch_calendar(cid, body.model_dump(exclude_unset=True))


@router.delete("/v1/calendars/{cid}", summary="Delete a calendar (its items moved or trashed)")
def delete_calendar(request: Request, cid: str, items: str = Query("", description="move:<calendar id> or trash")) -> dict:
    try:
        return cal(request).store.delete_calendar(cid, items)
    except ValueError as e:
        raise Invalid(str(e), "calendar_has_items") from None


# ---- items -------------------------------------------------------------------------------------------------------
@router.post("/v1/items", summary="Add an event or a to-do")
def add_item(request: Request, body: ItemIn, x_gaifa_origin: str | None = Header(None)) -> dict:
    return cal(request).items.create(_body(body), origin_of(x_gaifa_origin))


@router.get("/v1/items/{iid}", summary="One item (with its occurrence's fields when `occurrence` is given)")
def get_item(request: Request, iid: str, occurrence: str | None = None) -> dict:
    c = cal(request)
    item = c.store.get(iid)
    out = c.items.view(item)
    if occurrence:
        out["occurrence"] = R.occurrence(item, occurrence, c.store.overrides(iid).get(occurrence))
    return out


@router.patch("/v1/items/{iid}", summary="Change an item, one occurrence, or this and the following ones")
def patch_item(request: Request, iid: str, body: ItemIn, occurrence: str | None = None, scope: Scope = "all",
               x_gaifa_origin: str | None = Header(None)) -> dict:
    return cal(request).items.patch(iid, _body(body), origin_of(x_gaifa_origin), occurrence, scope)


@router.delete("/v1/items/{iid}", summary="Delete an item (to the trash), one occurrence, or this and the following ones")
def delete_item(request: Request, iid: str, occurrence: str | None = None, scope: Scope = "all",
                x_gaifa_origin: str | None = Header(None)) -> dict:
    return cal(request).items.delete(iid, origin_of(x_gaifa_origin), occurrence, scope)


@router.post("/v1/items/{iid}/done", summary="Complete a to-do (a repeating one's occurrence); undone=true reopens it")
def done_item(request: Request, iid: str, occurrence: str | None = None, undone: bool = False,
              x_gaifa_origin: str | None = Header(None)) -> dict:
    return cal(request).items.done(iid, origin_of(x_gaifa_origin), occurrence, undone)


@router.get("/v1/items/{iid}/next", summary="An item's next occurrence starting at or after `after` (default now)")
def next_occ(request: Request, iid: str, after: str | None = None) -> dict:
    c = cal(request)
    item = c.store.get(iid)
    t = T.from_query(after) if after else T.now_local()
    o = R.next_occurrence(item, c.store.overrides(iid), t)
    return {"item_id": iid, "next": o, "rev": c.store.rev}


@router.get("/v1/range", summary="Every occurrence overlapping [from, to), sorted")
def range_(request: Request, from_: str = Query(..., alias="from"), to: str = Query(...),
           calendars: str | None = None, kinds: str | None = None, project: str | None = None) -> dict:
    c = cal(request)
    frm, t = T.from_query(from_), T.from_query(to)
    if t <= frm or t - frm > timedelta(days=400):
        raise Invalid("the range is from < to, up to 400 days", "bad_range")
    occ = c.items.range(frm, t, calendars.split(",") if calendars else None, kinds.split(",") if kinds else None, project)
    return {"from": frm.isoformat(), "to": t.isoformat(), "occurrences": occ, "rev": c.store.rev}


@router.get("/v1/todos", summary="Open to-dos: undated, overdue and due soon")
def todos(request: Request, include_done: bool = False, days: int = Query(60, ge=1, le=400)) -> dict:
    c = cal(request)
    return {"todos": c.items.todos(include_done, days), "rev": c.store.rev}


@router.get("/v1/search", summary="Items whose title, notes or place has these words")
def search(request: Request, q: str = Query(..., min_length=1), limit: int = Query(30, ge=1, le=200)) -> dict:
    c = cal(request)
    return {"items": [c.items.view(i) for i in c.store.search(q, limit)]}


@router.get("/v1/trash", summary="Deleted items, kept 30 days")
def trash(request: Request) -> dict:
    c = cal(request)
    return {"items": [c.items.view(i) for i in c.store.trash()]}


@router.post("/v1/trash/{iid}/restore", summary="Restore an item from the trash")
def restore(request: Request, iid: str) -> dict:
    c = cal(request)
    with c.store.lock:
        item = c.store.get(iid, trashed=True)
        if item["deleted_at"] is None:
            raise Invalid("it isn't in the trash", "not_in_trash")
        c.store.update(iid, {"deleted_at": None})
        c.store.bump()
    return {"item": c.items.view(c.store.get(iid))}


@router.post("/v1/undo/{uid}", summary="Undo a write (each item put back as it was)")
def undo(request: Request, uid: str) -> dict:
    return {"undone": cal(request).store.undo(uid)}


# ---- words, settings -----------------------------------------------------------------------------------------------
@router.get("/v1/parse", summary="Read a date and time written in plain words (deterministic, no model)")
def parse(request: Request, text: str = Query(..., min_length=1, description="e.g. 'lunch w/ Sam Fri 1pm', 'every Tuesday at 9'"),
          kind: Literal["event", "todo"] = "event", whole: bool = Query(False, description="every word must be a date or time")) -> dict:
    s = cal(request).settings.get()
    try:
        p = W.parse(text, T.now_local(), kind=kind, date_order=s["date_order"], whole=whole)
    except W.Unreadable as e:
        raise Invalid(str(e), "unreadable_when", {"part": e.part}) from None
    if p.get("rrule"):
        p["repeat"] = R.describe(p["rrule"], p.get("start") or p.get("due"))
    return p


@router.get("/v1/settings", summary="Working hours, alert defaults, week start, date order, the agenda in the prompt")
def get_settings(request: Request) -> dict:
    return cal(request).settings.get()


@router.patch("/v1/settings", summary="Change settings")
def patch_settings(request: Request, body: dict = Body(...)) -> dict:
    try:
        out = cal(request).settings.patch(body)
    except ValueError as e:
        raise Invalid(str(e), "invalid_setting") from None
    cal(request).store.bump()
    return out
