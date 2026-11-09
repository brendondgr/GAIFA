"""Free time and day plans (calendar plan 1.6), deterministic: no model.

- Busy is every timed event whose `busy` isn't `free`; focus blocks count unless `include_focus` says they may
  be used. All-day events don't block (holidays, birthdays, trips are marked as such by you with times).
- Free time is never in the past: a range that starts before now starts now (rounded up to 5 minutes).
- A day plan places open to-dos in that day's free working time: overdue and soonest due first, then higher
  priority, then the ones with an estimate; each takes `estimate_min` (default 30) with 10-minute gaps.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from typing import Any

import timeutil as T

GAP_MIN = 10
DEFAULT_ESTIMATE = 30


def _round_up(t: float, minutes: int = 5) -> float:
    step = minutes * 60
    return math.ceil(t / step) * step


def busy(items: Any, frm: datetime, to: datetime, include_focus: bool = False) -> list[tuple[float, float]]:
    out = []
    for o in items.range(frm, to, kinds=["event"]):
        if o["all_day"] or o["busy"] == "free" or (o["busy"] == "focus" and include_focus):
            continue
        out.append((o["ts"], o["end_ts"]))
    out.sort()
    merged: list[tuple[float, float]] = []
    for a, b in out:
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    return merged


def windows(settings: dict[str, Any], frm: datetime, to: datetime, within: str) -> list[tuple[float, float]]:
    """The spans free time may fall in: the whole range, or each day's working hours inside it."""
    if within != "work":
        return [(frm.timestamp(), to.timestamp())]
    out = []
    d = frm.astimezone(T.local_tz()).date()
    end = to.astimezone(T.local_tz()).date()
    while d <= end:
        wh = settings["work_hours"][d.weekday()]
        if wh:
            a = datetime.combine(d, datetime.strptime(wh[0], "%H:%M").time()).replace(tzinfo=T.local_tz()).timestamp()
            b = datetime.combine(d, datetime.strptime(wh[1], "%H:%M").time()).replace(tzinfo=T.local_tz()).timestamp()
            a, b = max(a, frm.timestamp()), min(b, to.timestamp())
            if a < b:
                out.append((a, b))
        d += timedelta(days=1)
    return out


def free(items: Any, settings: dict[str, Any], frm: datetime, to: datetime, min_minutes: int = 30,
         within: str = "work", include_focus: bool = False, now: datetime | None = None) -> list[dict[str, Any]]:
    now_ts = _round_up((now or T.now_local()).timestamp())
    blocked = busy(items, frm, to, include_focus)
    slots = []
    for a, b in windows(settings, frm, to, within):
        a = max(a, now_ts)
        for s, e in blocked:
            if e <= a or s >= b:
                continue
            if s > a:
                slots.append((a, s))
            a = max(a, e)
        if a < b:
            slots.append((a, b))
    tz = T.local_tz()
    out = []
    for a, b in slots:
        mins = int((b - a) // 60)
        if mins >= min_minutes:
            out.append({"start": T.fmt_wall(datetime.fromtimestamp(a, tz).replace(tzinfo=None)),
                        "end": T.fmt_wall(datetime.fromtimestamp(b, tz).replace(tzinfo=None)),
                        "minutes": mins, "ts": a, "end_ts": b})
    return out


def plan_day(items: Any, settings: dict[str, Any], day: date, todo_ids: list[str] | None = None,
             now: datetime | None = None) -> dict[str, Any]:
    """A proposal's items (time blocks for to-dos) and the to-dos that didn't fit."""
    start, end = T.day_bounds(day)
    end_of_day = end.timestamp()
    ahead = max(60, (day - (now or T.now_local()).date()).days + 2)
    todos = [t for t in items.todos(horizon_days=ahead) if not t["done"]]
    if todo_ids:
        todos = [t for t in todos if t["item_id"] in todo_ids or t["id"] in todo_ids]
    else:
        todos = [t for t in todos if t["ts"] is None or t["ts"] < end_of_day]

    def rank(t: dict[str, Any]) -> tuple:
        return (t["ts"] is None, t["ts"] or 0, -(t.get("priority") or 0), t.get("estimate_min") is None)

    todos.sort(key=rank)
    slots = [[s["ts"], s["end_ts"]] for s in free(items, settings, start, end, 5, "work", False, now)]
    tz = T.local_tz()
    blocks, left = [], []
    for t in todos:
        need = (t.get("estimate_min") or DEFAULT_ESTIMATE) * 60
        for s in slots:
            if s[1] - s[0] >= need:
                a = s[0]
                blocks.append({"kind": "event", "title": t["title"],
                               "start": T.fmt_wall(datetime.fromtimestamp(a, tz).replace(tzinfo=None)),
                               "end": T.fmt_wall(datetime.fromtimestamp(a + need, tz).replace(tzinfo=None)),
                               "busy": "busy", "project_id": t.get("project_id"),
                               "notes": f"Time for the to-do \"{t['title']}\"",
                               "source": {"kind": "plan", "todo": t["item_id"], "occurrence": t.get("occurrence")}})
                s[0] = a + need + GAP_MIN * 60
                break
        else:
            left.append({"item_id": t["item_id"], "title": t["title"], "estimate_min": t.get("estimate_min") or DEFAULT_ESTIMATE})
    return {"items": blocks, "left": left}
