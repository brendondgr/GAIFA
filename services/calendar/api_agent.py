"""Routes for the agent (calendar plan 4.1–4.2): the preflight its calls go through (`[agent] limits`), and the
agenda its `calendar_agenda` tool reads (short rows: what a model needs, nothing more)."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Body, Query, Request

import timeutil as T
from api_items import cal
from items import Invalid
from limits import preflight

router = APIRouter()


@router.post("/v1/limits", summary="The preflight of one agent call: its action for the hub's mode table")
def limits(request: Request, body: dict = Body(...)) -> dict:
    c = cal(request)
    return preflight(c.store, c.settings.get(), str(body.get("tool") or ""), body.get("arguments") or {}, body.get("origin") or {})


def row(o: dict[str, Any]) -> dict[str, Any]:
    """An occurrence as the agent reads it."""
    r: dict[str, Any] = {"id": o["item_id"], "kind": o["kind"], "title": o["title"]}
    if o["kind"] == "todo":
        r["due"] = o.get("due")
        r["done"] = o.get("done")
    else:
        r["start"], r["end"] = o["start"], o["end"]
    if o.get("all_day"):
        r["all_day"] = True
    if o.get("recurring"):
        r["occurrence"] = o["occurrence"]
        r["repeats"] = True
    for k in ("location", "calendar", "project_id"):
        if o.get(k):
            r[k] = o[k]
    if o.get("busy") and o["busy"] != "busy":
        r["busy"] = o["busy"]
    return r


def day_of(word: str | None) -> date:
    today = T.now_local().date()
    if not word or word == "today":
        return today
    if word == "tomorrow":
        return today + timedelta(days=1)
    if word == "yesterday":
        return today - timedelta(days=1)
    try:
        return date.fromisoformat(word[:10])
    except ValueError:
        raise Invalid(f"day is today, tomorrow or YYYY-MM-DD, not {word!r}", "bad_day") from None


@router.get("/v1/agenda", summary="What's on: events and to-dos from a day for some days (short rows for the agent)")
def agenda(request: Request, day: str | None = Query(None, description="today (default), tomorrow, yesterday or YYYY-MM-DD; or from/to"),
           days: int = Query(1, ge=1, le=31, description="How many days from `day`"),
           from_: str | None = Query(None, alias="from", description="A start (ISO) instead of day"),
           to: str | None = Query(None, description="An end (ISO), with from"),
           todos: bool = Query(True, description="Also open to-dos with no date and overdue ones")) -> dict:
    c = cal(request)
    if from_:
        frm = T.from_query(from_)
        t = T.from_query(to) if to else frm + timedelta(days=days)
        if t <= frm or t - frm > timedelta(days=62):
            raise Invalid("the range is from < to, up to 62 days", "bad_range")
    else:
        d = day_of(day)
        frm, _ = T.day_bounds(d)
        _, t = T.day_bounds(d + timedelta(days=days - 1))
    occ = c.items.range(frm, t)
    out: dict[str, Any] = {"from": frm.isoformat(timespec="minutes"), "to": t.isoformat(timespec="minutes"),
                           "now": T.now_local().isoformat(timespec="minutes"), "items": [row(o) for o in occ]}
    if todos:
        open_ = [o for o in c.items.todos() if not o.get("done")]
        out["undated_todos"] = [{"id": o["item_id"], "title": o["title"]} for o in open_ if o.get("ts") is None][:30]
        out["overdue_todos"] = [row(o) for o in open_ if o.get("overdue")][:30]
    return out
