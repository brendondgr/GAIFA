"""Repeats (calendar plan 1.3): an item's occurrences in a range, and the rule changes that "this and following"
needs. Rules are RFC 5545 RRULE strings without DTSTART (`FREQ=WEEKLY;BYDAY=TU,TH`), expanded with dateutil from
the item's wall-clock start in its own zone.

An occurrence's key is its original start as a wall string (a date for all-day items): `<item id>@<key>` is its
id, and overrides and EXDATEs are keyed by it.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from dateutil.rrule import rrulestr

import timeutil as T

MAX_PER_ITEM = 2000
DAYS = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]
DAY_WORDS = {"MO": "Mon", "TU": "Tue", "WE": "Wed", "TH": "Thu", "FR": "Fri", "SA": "Sat", "SU": "Sun"}


def parts(rule: str) -> dict[str, str]:
    rule = rule.strip()
    if rule.upper().startswith("RRULE:"):
        rule = rule[6:]
    out = {}
    for p in rule.split(";"):
        if "=" in p:
            k, v = p.split("=", 1)
            out[k.strip().upper()] = v.strip()
    return out


def join(p: dict[str, str]) -> str:
    order = ["FREQ", "INTERVAL", "BYDAY", "BYMONTHDAY", "BYMONTH", "BYSETPOS", "WKST", "COUNT", "UNTIL"]
    keys = [k for k in order if k in p] + [k for k in p if k not in order]
    return ";".join(f"{k}={p[k]}" for k in keys)


def check(rule: str, anchor: str) -> str:
    """The rule, normalised; ValueError when dateutil can't read it or it has no FREQ."""
    p = parts(rule)
    if p.get("FREQ") not in ("DAILY", "WEEKLY", "MONTHLY", "YEARLY", "HOURLY"):
        raise ValueError(f"a repeat rule needs FREQ=DAILY|WEEKLY|MONTHLY|YEARLY (got {rule!r})")
    if "UNTIL" in p:
        p["UNTIL"] = _until_naive(p["UNTIL"], T.is_date(anchor))
    norm = join(p)
    _rule(norm, anchor)
    return norm


def _until_naive(v: str, all_day: bool) -> str:
    """UNTIL as a naive local value: a UTC `…Z` is read in the machine's zone (iCalendar files send those)."""
    v = v.strip()
    if v.endswith("Z"):
        d = datetime.strptime(v, "%Y%m%dT%H%M%SZ").replace(tzinfo=ZoneInfo("UTC")).astimezone(T.local_tz())
        return d.strftime("%Y%m%d") if all_day else d.strftime("%Y%m%dT%H%M%S")
    if all_day:
        return v[:8]
    return v if "T" in v else v + "T235959"


def _rule(rule: str, anchor: str) -> Any:
    return rrulestr(rule, dtstart=T.parse_wall(anchor), ignoretz=True)


def anchor_of(item: dict[str, Any]) -> str | None:
    return item.get("start") if item["kind"] == "event" else item.get("due")


def duration(item: dict[str, Any]) -> timedelta:
    if item["kind"] != "event" or not item.get("start"):
        return timedelta(0)
    if not item.get("end"):
        return timedelta(days=1) if item.get("all_day") else timedelta(hours=1)
    return T.parse_wall(item["end"]) - T.parse_wall(item["start"])


def keys_between(item: dict[str, Any], lo: datetime, hi: datetime) -> list[datetime]:
    """Naive starts in the item's own wall time with lo <= start <= hi (both naive, the item's zone)."""
    anchor = anchor_of(item)
    if not anchor:
        return []
    if not item.get("rrule"):
        a = T.parse_wall(anchor)
        return [a] if lo <= a <= hi else []
    out = []
    for d in _rule(item["rrule"], anchor).xafter(max(lo, T.parse_wall(anchor)) - timedelta(seconds=1), inc=True):
        if d > hi or len(out) >= MAX_PER_ITEM:
            break
        if d >= lo:
            out.append(d)
    return out


def is_occurrence(item: dict[str, Any], key: str) -> bool:
    try:
        k = T.parse_wall(key)
    except ValueError:
        return False
    if key in (item.get("exdates") or []):
        return False
    return k in keys_between(item, k, k)


def _zone(item: dict[str, Any]) -> Any:
    return T.local_tz() if item.get("all_day") else T.tz_of(item.get("tz"))


def occurrence(item: dict[str, Any], key: str, ov: dict[str, Any] | None = None) -> dict[str, Any]:
    """One occurrence as the page and the agent read it: times in this machine's zone, plus `ts`/`end_ts`."""
    f = (ov or {}).get("fields") or {}
    all_day = bool(item.get("all_day"))
    rec = bool(item.get("rrule"))
    out: dict[str, Any] = {
        "id": f"{item['id']}@{key}", "item_id": item["id"], "occurrence": key, "kind": item["kind"],
        "title": f.get("title", item["title"]), "notes": f.get("notes", item.get("notes") or ""),
        "location": f.get("location", item.get("location") or ""), "url": item.get("url") or "",
        "all_day": all_day, "tz": item.get("tz"), "calendar_id": item["calendar_id"], "recurring": rec,
        "project_id": item.get("project_id"), "busy": item.get("busy") or "busy", "priority": item.get("priority") or 0,
        "estimate_min": item.get("estimate_min"), "alerts": item.get("alerts") or [], "prep": item.get("prep"),
        "rrule": item.get("rrule"), "moved": bool(f.get("start")), "source": (item.get("source") or {}).get("kind"),
    }
    if item["kind"] == "event":
        start = f.get("start") or key
        end = f.get("end") or T.fmt_wall(T.parse_wall(start) + duration(item), all_day)
        out.update(start=T.in_local(start, item.get("tz"), all_day), end=T.in_local(end, item.get("tz"), all_day),
                   ts=T.ts(start, None if all_day else item.get("tz")), end_ts=T.ts(end, None if all_day else item.get("tz")))
        out["done"] = False
    else:
        due = f.get("due") or key
        is_d = T.is_date(due)
        out.update(due=T.in_local(due, item.get("tz"), is_d), start=T.in_local(due, item.get("tz"), is_d), end=None,
                   ts=T.ts(due, None if is_d else item.get("tz")), end_ts=None, all_day=is_d)
        done_at = f.get("done_at") if rec else item.get("done_at")
        out["done"], out["done_at"] = bool(done_at), done_at
    return out


def occurrences(item: dict[str, Any], ovs: dict[str, dict[str, Any]], frm: datetime, to: datetime) -> list[dict[str, Any]]:
    """The occurrences that overlap [frm, to) (aware). To-dos and zero-length items count when frm <= start < to.
    An occurrence moved into the range by an override is in it; one moved out isn't."""
    anchor = anchor_of(item)
    if not anchor:
        return []
    z = _zone(item)
    dur = duration(item)
    lo = frm.astimezone(z).replace(tzinfo=None) - dur - timedelta(days=1)
    hi = to.astimezone(z).replace(tzinfo=None) + timedelta(days=1)
    keys = {T.fmt_wall(d, bool(item.get("all_day"))) for d in keys_between(item, lo, hi)}
    for k, o in ovs.items():                      # moved in from outside the window
        if (o.get("fields") or {}).get("start") or (o.get("fields") or {}).get("due"):
            if k not in keys and is_occurrence(item, k):
                keys.add(k)
    ex = set(item.get("exdates") or [])
    out = []
    t0, t1 = frm.timestamp(), to.timestamp()
    for k in sorted(keys):
        if k in ex:
            continue
        ov = ovs.get(k)
        if ov and ov.get("cancelled"):
            continue
        o = occurrence(item, k, ov)
        end = o["end_ts"] if o["end_ts"] is not None else o["ts"]
        if (o["ts"] < t1 and end > t0) or (o["ts"] == end and t0 <= o["ts"] < t1):
            out.append(o)
    return out


def next_occurrence(item: dict[str, Any], ovs: dict[str, dict[str, Any]], after: datetime,
                    horizon_days: int = 800) -> dict[str, Any] | None:
    """The first occurrence starting at or after `after` (aware), looking a little over two years ahead."""
    step = timedelta(days=31)
    frm = after
    end = after + timedelta(days=horizon_days)
    while frm < end:
        occs = [o for o in occurrences(item, ovs, frm, frm + step) if o["ts"] >= after.timestamp()]
        if occs:
            return min(occs, key=lambda o: o["ts"])
        frm += step
    return None


# ---- "this and following" --------------------------------------------------------------------------------------
def split(item: dict[str, Any], key: str) -> tuple[str | None, str]:
    """The old series' rule ending before `key`, and the new series' rule from it (COUNT shared out).
    The old rule is None when `key` is the series' first occurrence (nothing stays behind)."""
    anchor = anchor_of(item) or key
    rule = item["rrule"]
    p = parts(rule)
    k = T.parse_wall(key)
    if k <= T.parse_wall(anchor):
        return None, rule
    new = dict(p)
    old = dict(p)
    if "COUNT" in p:
        before = len(keys_between(item, T.parse_wall(anchor), k - timedelta(seconds=1)))
        old["COUNT"] = str(before)
        new["COUNT"] = str(max(1, int(p["COUNT"]) - before))
        if before == 0:
            return None, rule
    else:
        old.pop("COUNT", None)
        old["UNTIL"] = (k - timedelta(days=1)).strftime("%Y%m%d") if T.is_date(key) else \
            (k - timedelta(seconds=1)).strftime("%Y%m%dT%H%M%S")
    return join(old), join(new)


def shift_keys(keys: list[str], delta: timedelta, all_day: bool) -> list[str]:
    return [T.fmt_wall(T.parse_wall(k) + delta, all_day) for k in keys]


# ---- words ---------------------------------------------------------------------------------------------------
def describe(rule: str | None, anchor: str | None = None) -> str:
    """A rule in words: "Every week on Tue, Thu", "Every 2 days until Dec 1", "Monthly on the last day"."""
    if not rule:
        return "Doesn't repeat"
    p = parts(rule)
    n = int(p.get("INTERVAL", "1") or 1)
    freq = p.get("FREQ", "")
    unit = {"DAILY": "day", "WEEKLY": "week", "MONTHLY": "month", "YEARLY": "year", "HOURLY": "hour"}.get(freq, "time")
    days = [d[-2:] for d in p.get("BYDAY", "").split(",") if d]
    if freq == "DAILY" and n == 1:
        s = "Every day"
    elif freq == "WEEKLY" and n == 1 and sorted(days, key=DAYS.index) == DAYS[:5]:
        s = "Every weekday"
    elif n == 1:
        s = {"WEEKLY": "Weekly", "MONTHLY": "Monthly", "YEARLY": "Yearly", "HOURLY": "Hourly"}.get(freq, "Every day")
    else:
        s = f"Every {n} {unit}s"
    if freq == "WEEKLY" and days and s != "Every weekday":
        s += " on " + ", ".join(DAY_WORDS.get(d, d) for d in sorted(days, key=lambda d: DAYS.index(d) if d in DAYS else 9))
    if freq == "MONTHLY":
        md = p.get("BYMONTHDAY")
        if md == "-1":
            s += " on the last day"
        elif md:
            s += f" on day {md}"
        elif p.get("BYDAY"):
            bd = p["BYDAY"]
            pos = bd[:-2] or p.get("BYSETPOS", "")
            nth = {"1": "first", "2": "second", "3": "third", "4": "fourth", "-1": "last"}.get(pos.lstrip("+"), pos)
            s += f" on the {nth} {DAY_WORDS.get(bd[-2:], bd[-2:])}"
        elif anchor:
            s += f" on day {T.parse_wall(anchor).day}"
    if "COUNT" in p:
        s += f", {p['COUNT']} times"
    elif "UNTIL" in p:
        u = p["UNTIL"]
        d = date(int(u[:4]), int(u[4:6]), int(u[6:8]))
        s += f" until {d.strftime('%b')} {d.day}, {d.year}"
    return s
