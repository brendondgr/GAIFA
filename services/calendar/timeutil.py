"""Times as the calendar keeps them: wall-clock strings with an IANA zone (calendar plan §2).

- A timed value is `YYYY-MM-DDTHH:MM` (seconds dropped), read in its item's `tz`.
- An all-day value is `YYYY-MM-DD`; an all-day event's `end` is the day after its last (exclusive, as in iCalendar).
- The machine's zone is `CALENDAR_TZ` when set (the tests), else the system's (tzlocal).
"""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo


def local_tz() -> ZoneInfo:
    name = os.environ.get("CALENDAR_TZ") or os.environ.get("TZ") or ""
    if name and "/" in name:
        try:
            return ZoneInfo(name.lstrip(":"))
        except Exception:  # noqa: BLE001: an unknown name falls back to the system's
            pass
    try:
        import tzlocal
        return ZoneInfo(tzlocal.get_localzone_name())
    except Exception:  # noqa: BLE001
        return ZoneInfo("UTC")


def tz_of(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name) if name else local_tz()
    except Exception:  # noqa: BLE001
        return local_tz()


def is_date(s: str | None) -> bool:
    return bool(s) and len(s) == 10


def parse_wall(s: str) -> datetime:
    """A wall time or a date, as a naive datetime (a date at 00:00)."""
    s = s.strip()
    if len(s) == 10:
        return datetime.fromisoformat(s)
    d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return d.replace(second=0, microsecond=0)


def fmt_wall(d: datetime | date, all_day: bool = False) -> str:
    if all_day or not isinstance(d, datetime):
        return (d.date() if isinstance(d, datetime) else d).isoformat()
    return d.strftime("%Y-%m-%dT%H:%M")


def norm_wall(s: str | None, tz: str | None = None) -> str | None:
    """A value from a caller: a date stays a date; an aware time is moved into `tz` and made a wall time."""
    if not s:
        return None
    s = s.strip()
    if len(s) == 10:
        date.fromisoformat(s)
        return s
    d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if d.tzinfo is not None:
        d = d.astimezone(tz_of(tz)).replace(tzinfo=None)
    return fmt_wall(d)


def aware(wall: str, tz: str | None) -> datetime:
    """A wall string in its zone, as an aware datetime (a date at its midnight)."""
    return parse_wall(wall).replace(tzinfo=tz_of(tz))


def ts(wall: str, tz: str | None) -> float:
    return aware(wall, tz).timestamp()


def in_local(wall: str, tz: str | None, all_day: bool = False) -> str:
    """The wall string as this machine shows it (all-day values aren't moved)."""
    if all_day or is_date(wall):
        return wall[:10]
    return fmt_wall(aware(wall, tz).astimezone(local_tz()).replace(tzinfo=None))


def now_local() -> datetime:
    return datetime.now(local_tz()).replace(second=0, microsecond=0)


def day_bounds(d: date) -> tuple[datetime, datetime]:
    """Local midnight to the next local midnight, aware."""
    tz = local_tz()
    start = datetime(d.year, d.month, d.day, tzinfo=tz)
    nxt = d + timedelta(days=1)
    return start, datetime(nxt.year, nxt.month, nxt.day, tzinfo=tz)


def from_query(s: str) -> datetime:
    """A `from`/`to` in a query: unix seconds, a date (local midnight) or an ISO time (local when naive)."""
    s = s.strip()
    try:
        return datetime.fromtimestamp(float(s), local_tz())
    except ValueError:
        pass
    d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=local_tz())
