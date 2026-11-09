"""Today's agenda for the agent's prompt (calendar plan 5.1): today's items, to-dos due today and overdue, all of
tomorrow, and (in a project's chats) the project's next 14 days.

The text depends only on the calendar and the date: it lists the whole day, never "what's left" or the time now,
so the prompt stays the same (and cached) all day until something changes. At most 40 lines.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

import timeutil as T

MAX_LINES = 40
PROJECT_DAYS = 14


def _day(d: date) -> str:
    return f"{d.strftime('%a')} {d.day} {d.strftime('%b')}"


def line(o: dict[str, Any], with_day: bool = False) -> str:
    rep = " ↻" if o.get("recurring") else ""
    cal = f" ({o['calendar']})" if o.get("calendar") else ""
    tag = f" [{o['item_id']}]"
    day = f"{_day(datetime.fromisoformat(o['start'][:10]).date())} " if with_day and o.get("start") else ""
    if o["kind"] == "todo":
        when = "to-do" if o.get("all_day") else f"to-do, due {o['due'][11:16]}"
        done = " (done)" if o.get("done") else ""
        return f"- {day}{when}: {o['title']}{done}{rep}{tag}"
    if o.get("all_day"):
        return f"- {day}all day: {o['title']}{cal}{rep}{tag}"
    return f"- {day}{o['start'][11:16]}–{o['end'][11:16]} {o['title']}{cal}{rep}{tag}"


def covers(o: dict[str, Any], d: date, a: datetime, b: datetime) -> bool:
    """Whether an occurrence is on day `d` (local bounds a, b): an all-day one by its dates, a timed one by overlap."""
    if o.get("all_day"):
        s = o["start"][:10]
        e = (o.get("end") or "")[:10] if o["kind"] == "event" else ""
        return s <= d.isoformat() < e if e else s == d.isoformat()
    end = o["end_ts"] if o.get("end_ts") is not None else o["ts"]
    return o["ts"] < b.timestamp() and (end > a.timestamp() or (end == o["ts"] and o["ts"] >= a.timestamp()))


def prompt_text(items: Any, settings: dict[str, Any], day: date, project: str | None = None) -> str:
    if not settings.get("agenda_in_prompt", True):
        return ""
    t0, t1 = T.day_bounds(day)
    _, t2 = T.day_bounds(day + timedelta(days=1))
    occ = items.range(t0, t2)
    today = [o for o in occ if covers(o, day, t0, t1)]
    tomorrow = [o for o in occ if covers(o, day + timedelta(days=1), t1, t2)]
    overdue = [o for o in items.todos() if not o.get("done") and o.get("ts") is not None and o["due"][:10] < day.isoformat()]
    out: list[str] = []
    out.append(f"Today, {_day(day)}:")
    out += [line(o) for o in today if o["kind"] == "event"] or ["- nothing"]
    due = [o for o in today if o["kind"] == "todo"]
    if due or overdue:
        out.append("To-dos due today and overdue:")
        out += [line(o) for o in due] + [line(o, with_day=True).replace("to-do", "overdue to-do", 1) for o in overdue]
    out.append(f"Tomorrow, {_day(day + timedelta(days=1))}:")
    out += [line(o) for o in tomorrow] or ["- nothing"]
    if project:
        p0, _ = T.day_bounds(day)
        _, p1 = T.day_bounds(day + timedelta(days=PROJECT_DAYS - 1))
        pocc = items.range(p0, p1, project=project)
        if pocc:
            out.append(f"This project's dates (next {PROJECT_DAYS} days):")
            out += [line(o, with_day=True) for o in pocc]
    if len(out) > MAX_LINES:
        left = len(out) - (MAX_LINES - 1)
        out = out[: MAX_LINES - 1] + [f"- … and {left} more (calendar_agenda lists them)"]
    return "\n".join(out)
