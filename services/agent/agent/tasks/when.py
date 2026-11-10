"""When a scheduled task runs (plan scheduled-tasks 1.1), in the machine's local time.

A schedule is one of:
- `{kind: "hourly", every: 1–24, minute: 0–59, from?: "HH:MM", to?: "HH:MM", weekdays?: bool}`: every `every` hours
  from 00:MM, only inside the window when there is one, only Monday to Friday with `weekdays`;
- `{kind: "daily" | "weekdays", time: "HH:MM"}`;
- `{kind: "weekly", day: 0–6 (Monday = 0), time}`;
- `{kind: "monthly", day: 1–31, time}`: a shorter month runs on its last day;
- `{kind: "once", at: "YYYY-MM-DDTHH:MM"}` (calendar 6.1): one run; after it, the task turns off;
- `{kind: "event", item: "c_…", before_min: 0–1440, title?}` (calendar 6.2): N minutes before each occurrence of a
  calendar item; its times come from the calendar mod (`event_due.py`), so `next_after` doesn't answer for it.

Local times go through `time.mktime`, so a time that a daylight-saving change skips moves to the next valid minute,
and a repeated hour runs once (the first).
"""

from __future__ import annotations

import calendar
import re
import time
from datetime import date, timedelta
from typing import Any

KINDS = ("hourly", "daily", "weekdays", "weekly", "monthly", "once", "event")
AT = re.compile(r"^(\d{4})-(\d{2})-(\d{2})T([01]\d|2[0-3]):([0-5]\d)$")
DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
HHMM = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
MISSED_MAX = 1000


def _hm(v: Any) -> tuple[int, int] | None:
    m = HHMM.match(str(v or ""))
    return (int(m[1]), int(m[2])) if m else None


def _int(v: Any, lo: int, hi: int) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi else None


def check(s: Any) -> list[str]:
    """What's wrong with a schedule (empty: it's fine)."""
    if not isinstance(s, dict):
        return ["the schedule must be an object"]
    kind = s.get("kind")
    if kind not in KINDS:
        return [f"kind must be one of {', '.join(KINDS)}"]
    out = []
    if kind == "once":
        m = AT.match(str(s.get("at") or ""))
        try:
            date(int(m[1]), int(m[2]), int(m[3])) if m else None
        except ValueError:
            m = None
        return [] if m else ["at must be a date and time, YYYY-MM-DDTHH:MM"]
    if kind == "event":
        if not str(s.get("item") or "").startswith("c_"):
            out.append("item must be a calendar item's id (c_…)")
        if _int(s.get("before_min", 0), 0, 1440) is None:
            out.append("before_min must be 0 to 1440 minutes")
        return out
    if kind == "hourly":
        if _int(s.get("every", 1), 1, 24) is None:
            out.append("every must be a whole number of hours, 1 to 24")
        if _int(s.get("minute", 0), 0, 59) is None:
            out.append("minute must be 0 to 59")
        for k in ("from", "to"):
            if s.get(k) not in (None, "") and _hm(s[k]) is None:
                out.append(f"{k} must be a time, HH:MM")
        if bool(s.get("from")) != bool(s.get("to")):
            out.append("a window needs both from and to")
        elif s.get("from") and _hm(s["from"]) and _hm(s["to"]) and _hm(s["from"]) > _hm(s["to"]):  # type: ignore[operator]
            out.append("the window's from must come before its to")
        if not isinstance(s.get("weekdays", False), bool):
            out.append("weekdays must be true or false")
        elif not _times(s):
            out.append("no hour of the day falls inside the window")
    else:
        if _hm(s.get("time")) is None:
            out.append("time must be HH:MM (24-hour)")
        if kind == "weekly" and _int(s.get("day"), 0, 6) is None:
            out.append("day must be 0 (Monday) to 6 (Sunday)")
        if kind == "monthly" and _int(s.get("day"), 1, 31) is None:
            out.append("day must be 1 to 31")
    return out


def _times(s: dict[str, Any]) -> list[tuple[int, int]]:
    """An hourly schedule's times in one day."""
    every, minute = int(s.get("every") or 1), int(s.get("minute") or 0)
    out = [(h, minute) for h in range(0, 24, every)]
    lo, hi = _hm(s.get("from")), _hm(s.get("to"))
    if lo and hi:
        out = [t for t in out if lo <= t <= hi]
    return out


def _on(s: dict[str, Any], d: date) -> list[tuple[int, int]]:
    """The schedule's times on day `d`."""
    kind = s["kind"]
    if kind == "once":
        m = AT.match(s["at"])
        assert m is not None
        return [(int(m[4]), int(m[5]))] if d == date(int(m[1]), int(m[2]), int(m[3])) else []
    if kind == "event":
        return []
    if kind == "hourly":
        return [] if s.get("weekdays") and d.weekday() >= 5 else _times(s)
    hm = _hm(s["time"])
    assert hm is not None
    if kind == "daily" or (kind == "weekdays" and d.weekday() < 5):
        return [hm]
    if kind == "weekly" and d.weekday() == s["day"]:
        return [hm]
    if kind == "monthly" and d.day == min(int(s["day"]), calendar.monthrange(d.year, d.month)[1]):
        return [hm]
    return []


def _ts(d: date, hm: tuple[int, int]) -> float:
    return time.mktime((d.year, d.month, d.day, hm[0], hm[1], 0, 0, 0, -1))


def next_after(s: dict[str, Any], t: float) -> float:
    """The first time the schedule is due strictly after `t`."""
    lt = time.localtime(t)
    d = date(lt.tm_year, lt.tm_mon, lt.tm_mday) - timedelta(days=1)    # a DST gap may push yesterday's last time past t
    for _ in range(400):
        for hm in _on(s, d):
            ts = _ts(d, hm)
            if ts > t:
                return ts
        d += timedelta(days=1)
    raise ValueError("the schedule never comes due")


def next_due(s: dict[str, Any], t: float) -> float | None:
    """`next_after`, or None when the schedule won't come due again by itself (a once that ran; an event's times,
    which the calendar answers)."""
    if s.get("kind") == "event":
        return None
    try:
        return next_after(s, t)
    except ValueError:
        return None


def missed(s: dict[str, Any], last_due: float, now: float) -> int:
    """How many times the schedule came due after `last_due` and up to `now` (capped at MISSED_MAX)."""
    n, t = 0, last_due
    while n < MISSED_MAX:
        nxt = next_due(s, t)
        if nxt is None:
            break
        t = nxt
        if t > now:
            break
        n += 1
    return n


def describe(s: dict[str, Any]) -> str:
    """The schedule in words: "Weekdays at 07:00", "Every 2 hours at :15, 08:00–18:00"."""
    kind = s.get("kind")
    if kind == "hourly":
        every, minute = int(s.get("every") or 1), int(s.get("minute") or 0)
        out = ("Every hour" if every == 1 else f"Every {every} hours") + f" at :{minute:02}"
        if s.get("from") and s.get("to"):
            out += f", {s['from']}–{s['to']}"
        return out + (", weekdays" if s.get("weekdays") else "")
    if kind == "once":
        m = AT.match(str(s.get("at") or ""))
        if not m:
            return "Once"
        d = date(int(m[1]), int(m[2]), int(m[3]))
        return f"Once, {DAYS[d.weekday()][:3]} {d.day} {d.strftime('%b')} {m[4]}:{m[5]}"
    if kind == "event":
        b = int(s.get("before_min") or 0)
        lead = "When" if not b else f"{b} min before" if b < 60 or b % 60 else f"{b // 60} h before"
        what = f"“{s['title']}”" if s.get("title") else "a calendar item"
        return f"{lead} {what}" + (" starts" if not b else "") + ", each time"
    at = s.get("time") or "?"
    if kind == "daily":
        return f"Every day at {at}"
    if kind == "weekdays":
        return f"Weekdays at {at}"
    if kind == "weekly":
        return f"{DAYS[int(s.get('day') or 0)]}s at {at}"
    if kind == "monthly":
        day = int(s.get("day") or 1)
        suffix = "th" if 10 <= day % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
        return f"Monthly on the {day}{suffix} at {at}" + (" (or the month's last day)" if day > 28 else "")
    return "?"
