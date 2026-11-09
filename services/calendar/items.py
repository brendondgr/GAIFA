"""What the routes do to items (calendar plan 1.4): create, change, complete and delete, with the scopes of a
repeating item (this one, this and following, all) and an undo record for each write."""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Any

import repeat as R
import timeutil as T
import when as W
from settings import Settings
from store import NotFound, Store

KINDS = ("event", "todo")
FIELDS = ("title", "notes", "location", "url", "start", "end", "all_day", "due", "priority", "estimate_min", "busy",
          "rrule", "alerts", "calendar", "project_id", "prep", "kind")


class Invalid(ValueError):
    def __init__(self, detail: str, code: str = "invalid_item", data: dict[str, Any] | None = None) -> None:
        super().__init__(detail)
        self.code, self.data = code, data or {}


def who(origin: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Who is writing: the agent (a tool call, with its chat) or you (the page)."""
    if origin.get("tool_call") or origin.get("thread"):
        return "agent", {"kind": "agent", "thread": origin.get("thread"), "task": origin.get("task")}
    return "you", {"kind": "you"}


def _resolve_when(body: dict[str, Any], kind: str, settings: dict[str, Any], now: datetime | None) -> dict[str, Any]:
    """`when` words → start/end/due/all_day/rrule; `repeat` words → rrule. Explicit fields win."""
    out: dict[str, Any] = {}
    if body.get("when"):
        try:
            p = W.parse(str(body["when"]), now, kind=kind, date_order=settings["date_order"], whole=True)
        except W.Unreadable as e:
            raise Invalid(str(e), "unreadable_when", {"part": e.part}) from None
        out = {k: p.get(k) for k in ("start", "end", "due", "all_day", "rrule") if p.get(k) is not None or k == "all_day"}
        out["_assumed"] = p["assumed"]
    if body.get("repeat"):
        words = str(body["repeat"])
        if not words.lower().startswith(("every", "daily", "weekly", "monthly", "yearly", "annually", "weekdays")):
            words = "every " + words
        try:
            p = W.parse(words, now, kind=kind, date_order=settings["date_order"], whole=True)
        except W.Unreadable as e:
            raise Invalid(f"repeat: {e}", "unreadable_repeat", {"part": e.part}) from None
        if not p.get("rrule"):
            raise Invalid(f"repeat: no repeat in {body['repeat']!r}", "unreadable_repeat")
        out["rrule"] = p["rrule"]
    return out


def normalise(store: Store, settings: dict[str, Any], body: dict[str, Any], base: dict[str, Any] | None = None,
              now: datetime | None = None) -> dict[str, Any]:
    """A create's or a patch's fields, checked and filled (`base`: the item being changed)."""
    kind = body.get("kind") or (base or {}).get("kind") or ("todo" if body.get("due") else "event")
    if kind not in KINDS:
        raise Invalid(f"kind is event or todo, not {kind!r}")
    f: dict[str, Any] = {k: body[k] for k in FIELDS if k in body and body[k] is not None and k != "calendar"}
    f["kind"] = kind
    f.update(_resolve_when(body, kind, settings, now))
    assumed = f.pop("_assumed", [])
    tz = (base or {}).get("tz") or T.local_tz().key
    f["tz"] = tz
    if "calendar" in body and body["calendar"]:
        try:
            f["calendar_id"] = store.find_calendar(str(body["calendar"]))["id"]
        except NotFound:
            raise Invalid(f"no calendar {body['calendar']!r}", "unknown_calendar") from None
    elif base is None:
        f["calendar_id"] = store.default_calendar()["id"]
    if "title" in f or base is None:
        title = str(f.get("title") or "").strip()
        if not 1 <= len(title) <= 200:
            raise Invalid("a title of 1–200 characters is needed", "invalid_title")
        f["title"] = title
    if len(str(f.get("notes") or "")) > 8000:
        raise Invalid("notes are up to 8,000 characters")
    for k in ("start", "end", "due"):
        if k in f and f[k]:
            try:
                f[k] = T.norm_wall(str(f[k]), tz)
            except ValueError:
                raise Invalid(f"{k}: {f[k]!r} isn't a date (YYYY-MM-DD) or a time (YYYY-MM-DDTHH:MM)", "invalid_time") from None
    merged = {**(base or {}), **f}
    if kind == "event":
        if not merged.get("start"):
            raise Invalid("an event needs a start (or `when`)", "no_start")
        all_day = T.is_date(merged["start"])
        f["all_day"] = all_day
        if base is None or "start" in f or "end" in f:
            start = T.parse_wall(merged["start"])
            if "end" not in f and base is not None and base.get("start") and "start" in f:
                end = start + R.duration(base)        # moving keeps the length
            elif merged.get("end") and T.is_date(merged["end"]) == all_day:
                end = T.parse_wall(merged["end"])
            else:
                end = start + (timedelta(days=1) if all_day else timedelta(hours=1))
            if end <= start:
                raise Invalid("the end must come after the start", "end_before_start")
            f["start"], f["end"] = T.fmt_wall(start, all_day), T.fmt_wall(end, all_day)
        f["due"] = None
    else:
        if "due" in f or base is None:
            f["all_day"] = bool(merged.get("due")) and T.is_date(merged["due"])
        if base is None or "kind" in body:
            f["start"] = f["end"] = None
    if "priority" in f and f["priority"] not in (0, 1, 2, 3):
        raise Invalid("priority is 0 (none) to 3 (high)")
    if "busy" in f and f["busy"] not in ("busy", "free", "focus"):
        raise Invalid("busy is busy, free or focus")
    if "alerts" in f:
        f["alerts"] = _alerts(f["alerts"])
    elif base is None:
        f["alerts"] = [{"before_min": m} for m in settings["event_alerts" if kind == "event" else "todo_alerts"]]
    if f.get("rrule"):
        anchor = merged.get("start") if kind == "event" else merged.get("due")
        if not anchor:
            raise Invalid("a repeating to-do needs a due date", "no_due")
        try:
            f["rrule"] = R.check(f["rrule"], f.get("start") or f.get("due") or anchor)
        except (ValueError, TypeError) as e:
            raise Invalid(f"repeat: {e}", "invalid_rrule") from None
    elif "rrule" in body and not body.get("rrule") and not body.get("repeat"):
        f["rrule"] = None
    f["_assumed"] = assumed
    return f


def _alerts(v: Any) -> list[dict[str, int]]:
    out = []
    for a in v or []:
        m = a.get("before_min") if isinstance(a, dict) else a
        if not isinstance(m, int) or not 0 <= m <= 40320:
            raise Invalid("alerts: minutes before, 0–40320")
        out.append({"before_min": m})
    if len(out) > 5:
        raise Invalid("up to five alerts")
    return sorted({a["before_min"]: a for a in out}.values(), key=lambda a: a["before_min"])


def _touch(item: dict[str, Any], by: str) -> str:
    """An item stays the agent's own only while only the agent changes it (calendar plan §2: its own test items)."""
    return "agent" if by == "agent" and item.get("touched_by") == "agent" else "you"


class Items:
    def __init__(self, store: Store, settings: Settings) -> None:
        self.store, self.settings = store, settings

    def _undo_path(self, uid: str) -> str:
        return f"/api/s/calendar/v1/undo/{uid}"

    def create(self, body: dict[str, Any], origin: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
        by, source = who(origin)
        with self.store.lock:
            f = normalise(self.store, self.settings.get(), body, now=now)
            assumed = f.pop("_assumed")
            f["source"] = body.get("source") or source
            f["touched_by"] = by
            item = self.store.insert(f)
            uid = self.store.record_undo([{"id": item["id"], "row": None, "overrides": {}}])
            self.store.bump()
        return {"item": self.view(item), "undo": self._undo_path(uid), "assumed": assumed}

    def view(self, item: dict[str, Any]) -> dict[str, Any]:
        """An item as the API answers it: its fields, its calendar's name and colour, its repeat in words."""
        out = {k: v for k, v in item.items() if k not in ("touched_by",)}
        try:
            cal = self.store.calendar(item["calendar_id"])
            out["calendar"], out["color"] = cal["name"], cal["color"]
        except NotFound:
            out["calendar"], out["color"] = None, None
        out["repeat"] = R.describe(item.get("rrule"), R.anchor_of(item)) if item.get("rrule") else None
        out["by_agent"] = item.get("touched_by") == "agent"
        return out

    def patch(self, iid: str, body: dict[str, Any], origin: dict[str, Any], occurrence: str | None = None,
              scope: str = "all", now: datetime | None = None) -> dict[str, Any]:
        by, _ = who(origin)
        with self.store.lock:
            item = self.store.get(iid)
            if occurrence and not item.get("rrule"):
                occurrence, scope = None, "all"
            if occurrence and not R.is_occurrence(item, occurrence):
                raise Invalid(f"{occurrence} isn't an occurrence of {iid}", "no_occurrence")
            snaps_ids = [iid]
            if scope == "this" and occurrence:
                f = normalise(self.store, self.settings.get(), {**body, "kind": item["kind"]}, base=item, now=now)
                assumed = f.pop("_assumed")
                snap = self.store.snapshot(snaps_ids)
                ov = {k: f[k] for k in ("title", "notes", "location", "start", "end", "due")
                      if f.get(k) is not None and (k in body or "when" in body)}
                self.store.set_override(iid, occurrence, ov)
                out_item = self.store.get(iid)
            elif scope == "following" and occurrence:
                old_rule, new_rule = R.split(item, occurrence)
                if old_rule is None:
                    return self.patch(iid, body, origin, None, "all", now)
                f = normalise(self.store, self.settings.get(), body, base={**item, "rrule": new_rule}, now=now)
                assumed = f.pop("_assumed")
                delta = timedelta(0)
                new_anchor = occurrence
                if item["kind"] == "event":
                    dur = R.duration(item)
                    start = f.get("start") or occurrence
                    f.setdefault("start", start)
                    f.setdefault("end", T.fmt_wall(T.parse_wall(start) + dur, item["all_day"]))
                    delta = T.parse_wall(f["start"]) - T.parse_wall(occurrence)
                    new_anchor = f["start"]
                else:
                    f.setdefault("due", occurrence)
                new_fields = {**{k: item[k] for k in item if k not in ("id", "created", "updated", "deleted_at")}, **f,
                              "rrule": f.get("rrule", new_rule)}
                new_fields["rrule"] = R.check(new_fields["rrule"], new_anchor) if new_fields["rrule"] else None
                new = self.store.insert(new_fields)
                snaps_ids.append(new["id"])
                snap = [*self.store.snapshot([iid]), {"id": new["id"], "row": None, "overrides": {}}]
                ovs = self.store.overrides(iid)
                keep = {k: o for k, o in ovs.items() if T.parse_wall(k) < T.parse_wall(occurrence)}
                move = {k: o for k, o in ovs.items() if k not in keep}
                self.store.update(iid, {"rrule": old_rule})
                self.store.replace_overrides(iid, keep)
                self.store.replace_overrides(new["id"], {R.shift_keys([k], delta, item["all_day"])[0]: o for k, o in move.items()})
                ex = [k for k in item.get("exdates") or [] if T.parse_wall(k) >= T.parse_wall(occurrence)]
                self.store.update(iid, {"exdates": [k for k in item.get("exdates") or [] if k not in ex]})
                self.store.update(new["id"], {"exdates": R.shift_keys(ex, delta, item["all_day"]), "touched_by": _touch(item, by)})
                out_item = self.store.get(new["id"])
            else:
                f = normalise(self.store, self.settings.get(), body, base=item, now=now)
                assumed = f.pop("_assumed")
                snap = self.store.snapshot(snaps_ids)
                if item.get("rrule") and item["kind"] == "event" and "start" in f and f["start"] != item["start"]:
                    delta = T.parse_wall(f["start"]) - T.parse_wall(item["start"])     # move the series: keys follow
                    ovs = self.store.overrides(iid)
                    self.store.replace_overrides(iid, {R.shift_keys([k], delta, item["all_day"])[0]: o for k, o in ovs.items()})
                    f["exdates"] = R.shift_keys(item.get("exdates") or [], delta, item["all_day"])
                out_item = self.store.update(iid, f)
            if scope != "following":
                self.store.update(iid, {"touched_by": _touch(item, by)})
                out_item = self.store.get(out_item["id"])
            uid = self.store.record_undo(snap)
            self.store.bump()
        return {"item": self.view(out_item), "undo": self._undo_path(uid), "assumed": assumed, "scope": scope}

    def delete(self, iid: str, origin: dict[str, Any], occurrence: str | None = None, scope: str = "all") -> dict[str, Any]:
        with self.store.lock:
            item = self.store.get(iid)
            snap = self.store.snapshot([iid])
            if occurrence and item.get("rrule") and scope in ("this", "following"):
                if not R.is_occurrence(item, occurrence):
                    raise Invalid(f"{occurrence} isn't an occurrence of {iid}", "no_occurrence")
                if scope == "this":
                    self.store.update(iid, {"exdates": sorted({*(item.get("exdates") or []), occurrence})})
                    what = "occurrence"
                else:
                    old_rule, _ = R.split(item, occurrence)
                    if old_rule is None:
                        self.store.update(iid, {"deleted_at": time.time()})
                        what = "item"
                    else:
                        self.store.update(iid, {"rrule": old_rule})
                        what = "following"
            else:
                self.store.update(iid, {"deleted_at": time.time()})
                what = "item"
            uid = self.store.record_undo(snap)
            self.store.bump()
        return {"deleted": what, "item_id": iid, "occurrence": occurrence, "undo": self._undo_path(uid),
                "note": "moved to the trash, kept 30 days" if what == "item" else None}

    def done(self, iid: str, origin: dict[str, Any], occurrence: str | None = None, undone: bool = False) -> dict[str, Any]:
        by, _ = who(origin)
        with self.store.lock:
            item = self.store.get(iid)
            if item["kind"] != "todo":
                raise Invalid("only to-dos are done", "not_a_todo")
            snap = self.store.snapshot([iid])
            at = None if undone else time.time()
            if item.get("rrule"):
                if not occurrence:
                    nxt = self.next_open(item)
                    if nxt is None:
                        raise Invalid("no open occurrence to complete", "no_occurrence")
                    occurrence = nxt
                if not R.is_occurrence(item, occurrence):
                    raise Invalid(f"{occurrence} isn't an occurrence of {iid}", "no_occurrence")
                self.store.set_override(iid, occurrence, {"done_at": at})
            else:
                self.store.update(iid, {"done_at": at})
            self.store.update(iid, {"touched_by": _touch(item, by)})
            uid = self.store.record_undo(snap)
            self.store.bump()
        return {"item": self.view(self.store.get(iid)), "occurrence": occurrence, "done": not undone,
                "undo": self._undo_path(uid)}

    def next_open(self, item: dict[str, Any]) -> str | None:
        """A repeating to-do's first occurrence not done (the oldest overdue one, else the next)."""
        ovs = self.store.overrides(item["id"])
        anchor = T.aware(R.anchor_of(item) or "", item.get("tz") if not item.get("all_day") else None)
        frm = anchor
        for _ in range(40):
            to = frm + timedelta(days=62)
            for o in R.occurrences(item, ovs, frm, to):
                if not o["done"]:
                    return o["occurrence"]
            frm = to
        return None

    def range(self, frm: datetime, to: datetime, calendars: list[str] | None = None,
              kinds: list[str] | None = None, project: str | None = None, include_hidden: bool = False) -> list[dict[str, Any]]:
        """Every occurrence overlapping [frm, to), sorted, with its calendar's name and colour."""
        cals = {c["id"]: c for c in self.store.calendars()}
        if not calendars and not include_hidden:
            calendars = [c for c, v in cals.items() if not v["hidden"]]
        items = self.store.items(calendars=calendars, kinds=kinds, project=project)
        ovs = self.store.all_overrides([i["id"] for i in items if i.get("rrule")])
        out = []
        for it in items:
            for o in R.occurrences(it, ovs.get(it["id"], {}), frm, to):
                c = cals.get(it["calendar_id"]) or {}
                o["calendar"], o["color"] = c.get("name"), c.get("color")
                o["by_agent"] = it.get("touched_by") == "agent"
                out.append(o)
        out.sort(key=lambda o: (o["ts"], not o["all_day"], o["title"].lower()))
        return out

    def todos(self, include_done: bool = False, horizon_days: int = 60) -> list[dict[str, Any]]:
        """Open to-dos: undated ones, overdue and due ones up to `horizon_days` ahead (a repeating one's open
        occurrences, the oldest overdue first)."""
        now = T.now_local()
        out = []
        cals = {c["id"]: c for c in self.store.calendars()}
        for it in self.store.items(kinds=["todo"]):
            c = cals.get(it["calendar_id"]) or {}
            if not it.get("due"):
                if include_done or not it.get("done_at"):
                    out.append({**self.view(it), "id": it["id"], "item_id": it["id"], "occurrence": None,
                                "done": bool(it.get("done_at")), "ts": None})
                continue
            frm = T.aware(it["due"], None if it.get("all_day") else it["tz"]) if not it.get("rrule") else now - timedelta(days=60)
            occs = R.occurrences(it, self.store.overrides(it["id"]), min(frm, now - timedelta(days=60)), now + timedelta(days=horizon_days))
            for o in occs:
                if o["done"] and not include_done:
                    continue
                o["calendar"], o["color"] = c.get("name"), c.get("color")
                o["overdue"] = not o["done"] and o["ts"] < (now.timestamp() if not o["all_day"] else
                                                           T.day_bounds(now.date())[0].timestamp())
                out.append(o)
                if it.get("rrule") and not o["overdue"]:
                    break                                      # a repeating to-do: its overdue ones and the next
        out.sort(key=lambda o: (o["ts"] is None, o["ts"] or 0, -(o.get("priority") or 0)))
        return out
