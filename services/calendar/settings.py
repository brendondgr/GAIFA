"""The calendar's settings (calendar plan 1.6): `CALENDAR_STATE/settings.json`, which `gaifa backup` keeps."""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

DEFAULTS: dict[str, Any] = {
    # per weekday, Mon = 0: [from, to] or None for a day off
    "work_hours": [["09:00", "17:00"]] * 5 + [None, None],
    "event_alerts": [10],          # minutes before an event
    "todo_alerts": [0],            # minutes before a to-do's time
    "allday_alert": "09:00",       # an all-day event's alert, the day before; an all-day to-do's, that day
    "week_start": 0,               # 0 = Monday, 6 = Sunday
    "date_order": "mdy",           # how 11/12 reads: mdy | dmy
    "agenda_in_prompt": True,      # today's and tomorrow's items in every chat's prompt (plan 5)
    "default_view": "week",
}
HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class Settings:
    def __init__(self, state_dir: str | os.PathLike[str]) -> None:
        self.path = Path(state_dir) / "settings.json"

    def get(self) -> dict[str, Any]:
        try:
            saved = json.loads(self.path.read_text())
        except (OSError, ValueError):
            saved = {}
        return {**DEFAULTS, **{k: v for k, v in saved.items() if k in DEFAULTS}}

    def patch(self, changes: dict[str, Any]) -> dict[str, Any]:
        cur = self.get()
        for k, v in changes.items():
            if k not in DEFAULTS:
                raise ValueError(f"unknown setting {k!r}")
            cur[k] = check(k, v)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".settings-")
        with os.fdopen(fd, "w") as f:
            json.dump({k: cur[k] for k in DEFAULTS if cur[k] != DEFAULTS[k]}, f, indent=1)
        os.replace(tmp, self.path)
        return cur


def check(k: str, v: Any) -> Any:
    if k == "work_hours":
        if not isinstance(v, list) or len(v) != 7:
            raise ValueError("work_hours: seven entries, Monday first, each [from, to] or null")
        for d in v:
            if d is not None and (len(d) != 2 or not all(isinstance(x, str) and HHMM.match(x) for x in d) or d[0] >= d[1]):
                raise ValueError(f"work_hours: {d!r} isn't [\"HH:MM\", \"HH:MM\"] with from before to")
        return v
    if k in ("event_alerts", "todo_alerts"):
        if not isinstance(v, list) or len(v) > 5 or not all(isinstance(x, int) and 0 <= x <= 40320 for x in v):
            raise ValueError(f"{k}: up to five whole minutes before, 0–40320")
        return sorted(set(v))
    if k == "allday_alert":
        if not (isinstance(v, str) and HHMM.match(v)):
            raise ValueError("allday_alert: HH:MM")
        return v
    if k == "week_start":
        if v not in (0, 6):
            raise ValueError("week_start: 0 (Monday) or 6 (Sunday)")
        return v
    if k == "date_order":
        if v not in ("mdy", "dmy"):
            raise ValueError("date_order: mdy or dmy")
        return v
    if k == "agenda_in_prompt":
        return bool(v)
    if k == "default_view":
        if v not in ("day", "week", "month", "agenda"):
            raise ValueError("default_view: day, week, month or agenda")
        return v
    return v
