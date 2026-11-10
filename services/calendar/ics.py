"""`.ics` import and export (calendar plan 1.7), with the `icalendar` library.

Import reads VEVENTs and VTODOs (RRULE, EXDATE, RECURRENCE-ID overrides, VALARM, TZID and all-day dates) into a
proposal; what it can't use is listed as skipped with the reason. An item whose UID was imported before is
marked `already` (left unticked). Export writes VEVENT/VTODO with their TZID, overrides and alarms.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

import icalendar

import repeat as R
import timeutil as T
from store import Store

MAX_BYTES = 5 * 1024 * 1024


def _zone_name(d: datetime) -> str | None:
    tz = d.tzinfo
    if tz is None:
        return None
    key = getattr(tz, "key", None) or getattr(tz, "zone", None)
    if key:
        return str(key)
    return None


def _wall(v: Any, tz: str | None) -> tuple[str, str | None, bool]:
    """(wall string, zone, all_day) for a DTSTART/DTEND/DUE value; an aware time without an IANA name is moved
    into this machine's zone."""
    if isinstance(v, datetime):
        if v.tzinfo is None:
            return T.fmt_wall(v), tz, False
        name = _zone_name(v)
        if name and name != "UTC":
            return T.fmt_wall(v.replace(tzinfo=None)), name, False
        local = v.astimezone(T.local_tz())
        return T.fmt_wall(local.replace(tzinfo=None)), T.local_tz().key, False
    if isinstance(v, date):
        return v.isoformat(), tz, True
    raise ValueError(f"not a date: {v!r}")


def _key(v: Any, tz: str | None, all_day: bool) -> str:
    """A RECURRENCE-ID or EXDATE value as the series' occurrence key (a wall time in the series' zone)."""
    if all_day:
        return (v.date() if isinstance(v, datetime) else v).isoformat()
    if isinstance(v, datetime) and v.tzinfo is not None:
        return T.fmt_wall(v.astimezone(T.tz_of(tz)).replace(tzinfo=None))
    return T.fmt_wall(v)


def _alarms(comp: Any, start: Any) -> list[dict[str, int]]:
    out = []
    for a in comp.walk("VALARM"):
        trig = a.get("TRIGGER")
        if trig is None:
            continue
        d = trig.dt
        if isinstance(d, timedelta):
            mins = int(-d.total_seconds() // 60)
        elif isinstance(d, datetime) and isinstance(start, datetime):
            s = start if start.tzinfo else start.replace(tzinfo=T.local_tz())
            mins = int((s - (d if d.tzinfo else d.replace(tzinfo=T.local_tz()))).total_seconds() // 60)
        else:
            continue
        if 0 <= mins <= 40320:
            out.append({"before_min": mins})
    return sorted({a["before_min"]: a for a in out}.values(), key=lambda a: a["before_min"])[:5]


def _text(comp: Any, k: str) -> str:
    v = comp.get(k)
    return str(v) if v is not None else ""


def read(data: bytes | str, store: Store) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(items, skipped) from an .ics file: each item's fields as the store takes them."""
    if isinstance(data, str):
        data = data.encode()
    if len(data) > MAX_BYTES:
        raise ValueError("an .ics file is up to 5 MB")
    try:
        cals = icalendar.Calendar.from_ical(data, multiple=True)
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"not an .ics file: {e}") from None
    known = {(i.get("source") or {}).get("ref") for i in store.items() if (i.get("source") or {}).get("kind") == "ics"}
    local = T.local_tz().key
    masters: dict[str, dict[str, Any]] = {}
    moved: list[tuple[str, Any, dict[str, Any], bool]] = []
    items, skipped = [], []
    for cal in cals:
        for comp in cal.walk():
            if comp.name not in ("VEVENT", "VTODO"):
                continue
            title = _text(comp, "SUMMARY").strip() or "(no title)"
            uid = _text(comp, "UID") or None
            try:
                if comp.name == "VEVENT":
                    ds = comp.get("DTSTART")
                    if ds is None:
                        skipped.append({"title": title, "why": "no start"})
                        continue
                    start, tz, all_day = _wall(ds.dt, local)
                    e = comp["DTEND"].dt if comp.get("DTEND") is not None else None
                    if e is not None and isinstance(e, datetime) == isinstance(ds.dt, datetime):
                        end = _key(e, tz, all_day) if isinstance(e, datetime) else e.isoformat()
                    elif comp.get("DURATION") is not None:
                        end = T.fmt_wall(T.parse_wall(start) + comp["DURATION"].dt, all_day)
                    else:
                        end = None
                    if end is None or T.parse_wall(end) <= T.parse_wall(start):
                        end = T.fmt_wall(T.parse_wall(start) + (timedelta(days=1) if all_day else timedelta(hours=1)), all_day)
                    f: dict[str, Any] = {"kind": "event", "title": title[:200], "start": start, "end": end, "all_day": all_day,
                                         "tz": tz or local, "busy": "free" if _text(comp, "TRANSP").upper() == "TRANSPARENT" else "busy"}
                    anchor_dt = ds.dt
                else:
                    due = comp.get("DUE") or comp.get("DTSTART")
                    f = {"kind": "todo", "title": title[:200], "tz": local, "all_day": False, "start": None, "end": None}
                    anchor_dt = due.dt if due is not None else None
                    if due is not None:
                        f["due"], f["tz"], f["all_day"] = _wall(due.dt, local)
                        f["tz"] = f["tz"] or local
                    pr = int(comp.get("PRIORITY") or 0)
                    f["priority"] = 0 if pr == 0 else 3 if pr <= 4 else 2 if pr == 5 else 1
                    if comp.get("COMPLETED") is not None or _text(comp, "STATUS").upper() == "COMPLETED":
                        c = comp.get("COMPLETED")
                        f["done_at"] = c.dt.timestamp() if c is not None and isinstance(c.dt, datetime) else datetime.now().timestamp()
                f["notes"] = _text(comp, "DESCRIPTION")[:8000]
                f["location"] = _text(comp, "LOCATION")[:500]
                f["url"] = _text(comp, "URL")[:1000]
                f["alerts"] = _alarms(comp, anchor_dt)
                rid = comp.get("RECURRENCE-ID")
                if rid is not None:
                    moved.append((uid or "", rid.dt, f, _text(comp, "STATUS").upper() == "CANCELLED"))
                    continue
                if _text(comp, "STATUS").upper() == "CANCELLED":
                    skipped.append({"title": title, "why": "cancelled"})
                    continue
                if comp.get("RRULE") is not None:
                    anchor = f.get("start") or f.get("due")
                    if not anchor:
                        skipped.append({"title": title, "why": "repeats with no start"})
                        continue
                    rule = comp["RRULE"].to_ical().decode()
                    try:
                        f["rrule"] = R.check(rule, anchor)
                    except (ValueError, TypeError) as e:
                        skipped.append({"title": title, "why": f"a repeat rule it can't read ({e})"})
                        continue
                    ex = []
                    exd = comp.get("EXDATE")
                    for e in (exd if isinstance(exd, list) else [exd] if exd is not None else []):
                        for d in e.dts:
                            ex.append(_key(d.dt, f["tz"], bool(f.get("all_day"))))
                    f["exdates"] = sorted(set(ex))
                f["source"] = {"kind": "ics", "ref": uid}
                f["overrides"] = {}
                row = {**f, "already": bool(uid and uid in known)}
                if uid:
                    masters[uid] = row
                items.append(row)
            except Exception as e:  # noqa: BLE001: one bad entry doesn't stop the file
                skipped.append({"title": title, "why": f"couldn't read it ({type(e).__name__}: {e})"[:200]})
    for uid, rid, f, cancelled in moved:
        m = masters.get(uid)
        if m is None:
            skipped.append({"title": f["title"], "why": "a changed occurrence of a series not in the file"})
            continue
        key = _key(rid, m["tz"], bool(m.get("all_day")))
        fields = {} if cancelled else {k: f[k] for k in ("title", "start", "end", "due", "notes", "location") if f.get(k) and f.get(k) != m.get(k)}
        m["overrides"][key] = {"fields": fields, "cancelled": cancelled}
    return items, skipped


def _dt(wall: str, tz: str | None, all_day: bool) -> Any:
    if all_day or T.is_date(wall):
        return date.fromisoformat(wall[:10])
    return T.parse_wall(wall).replace(tzinfo=T.tz_of(tz))


def write(store: Store, items: list[dict[str, Any]]) -> bytes:
    cal = icalendar.Calendar()
    cal.add("prodid", "-//GAIFA//Calendar//EN")
    cal.add("version", "2.0")
    ovs = store.all_overrides([i["id"] for i in items])
    for it in items:
        uid = (it.get("source") or {}).get("ref") if (it.get("source") or {}).get("kind") == "ics" else None
        uid = uid or f"{it['id']}@gaifa"
        comp = icalendar.Event() if it["kind"] == "event" else icalendar.Todo()
        _fill(comp, it, uid)
        if it.get("rrule"):
            comp.add("rrule", icalendar.vRecur.from_ical(it["rrule"]))
            for k in it.get("exdates") or []:
                comp.add("exdate", _dt(k, it["tz"], bool(it.get("all_day"))))
        cal.add_component(comp)
        for key, o in (ovs.get(it["id"]) or {}).items():
            occ = R.occurrence(it, key, o)
            sub = icalendar.Event() if it["kind"] == "event" else icalendar.Todo()
            fields = {**it, "title": occ["title"], "notes": occ["notes"], "location": occ["location"], "rrule": None,
                      "start": (o.get("fields") or {}).get("start") or key if it["kind"] == "event" else None,
                      "end": (o.get("fields") or {}).get("end") or T.fmt_wall(T.parse_wall(key) + R.duration(it), bool(it.get("all_day"))) if it["kind"] == "event" else None,
                      "due": (o.get("fields") or {}).get("due") or key if it["kind"] == "todo" else None,
                      "done_at": (o.get("fields") or {}).get("done_at")}
            _fill(sub, fields, uid)
            sub.add("recurrence-id", _dt(key, it["tz"], bool(it.get("all_day"))))
            if o.get("cancelled"):
                sub.add("status", "CANCELLED")
            cal.add_component(sub)
    return cal.to_ical()


def _fill(comp: Any, it: dict[str, Any], uid: str) -> None:
    comp.add("uid", uid)
    comp.add("summary", it["title"])
    comp.add("dtstamp", datetime.now(T.local_tz()))
    all_day = bool(it.get("all_day"))
    if it["kind"] == "event":
        comp.add("dtstart", _dt(it["start"], it["tz"], all_day))
        comp.add("dtend", _dt(it["end"], it["tz"], all_day))
        if it.get("busy") == "free":
            comp.add("transp", "TRANSPARENT")
    else:
        if it.get("due"):
            comp.add("due", _dt(it["due"], it["tz"], T.is_date(it["due"])))
        if it.get("done_at"):
            comp.add("status", "COMPLETED")
            comp.add("completed", datetime.fromtimestamp(it["done_at"], T.local_tz()))
        if it.get("priority"):
            comp.add("priority", {3: 1, 2: 5, 1: 9}[it["priority"]])
    for k, v in (("description", it.get("notes")), ("location", it.get("location")), ("url", it.get("url"))):
        if v:
            comp.add(k, v)
    for a in it.get("alerts") or []:
        al = icalendar.Alarm()
        al.add("action", "DISPLAY")
        al.add("description", it["title"])
        al.add("trigger", timedelta(minutes=-int(a["before_min"])))
        comp.add_component(al)
