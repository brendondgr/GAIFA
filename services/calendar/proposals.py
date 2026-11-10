"""Proposals (calendar plan 4.3): items the user ticks and adds, from the agent (dates read from a document), an
`.ics` import, or a day plan. Making one adds nothing to the calendar; accepting the ticked ones adds them in one
undo. Each proposed item is checked when the proposal is made, so the card shows exact dates, and items that
couldn't be read are kept with their problem (they can't be ticked)."""

from __future__ import annotations

import json
import time
from typing import Any

import items as I
from store import NotFound, new_id

MAX_ITEMS = 500


class Proposals:
    def __init__(self, cal: Any) -> None:
        self.cal = cal

    @property
    def store(self) -> Any:
        return self.cal.store

    def create(self, kind: str, raw: list[dict[str, Any]], source: dict[str, Any] | None = None,
               skipped: list[dict[str, Any]] | None = None, checked: bool = False) -> dict[str, Any]:
        """`checked`: the items are already normalised (an import); else each goes through `items.normalise`."""
        if len(raw) > MAX_ITEMS:
            raise I.Invalid(f"up to {MAX_ITEMS} items in one proposal", "too_many")
        settings = self.cal.settings.get()
        out = []
        for n, it in enumerate(raw, 1):
            row: dict[str, Any] = {"pid": str(n)}
            try:
                if checked:
                    f = dict(it)
                else:
                    body = {k: v for k, v in it.items() if k not in ("source", "overrides", "exdates")}
                    f = I.normalise(self.store, settings, body)
                    row["assumed"] = f.pop("_assumed", [])
                f.pop("_assumed", None)
                if it.get("source"):
                    f["source"] = it["source"]
                row["fields"] = f
                row["already"] = bool(it.get("already"))
            except I.Invalid as e:
                row["problem"] = {"detail": str(e), "code": e.code, **e.data}
                row["fields"] = {k: it.get(k) for k in ("title", "when", "start", "end", "due", "kind") if it.get(k) is not None}
            out.append(row)
        pid = new_id("pr")
        with self.store.lock:
            self.store.db.execute("INSERT INTO proposals(id, kind, items, source, skipped, created) VALUES (?,?,?,?,?,?)",
                                  (pid, kind, json.dumps(out), json.dumps(source or {}), json.dumps(skipped or []), time.time()))
            self.store.db.execute("DELETE FROM proposals WHERE created < ?", (time.time() - 30 * 86400,))
        return self.get(pid)

    def get(self, pid: str) -> dict[str, Any]:
        r = self.store.db.execute("SELECT * FROM proposals WHERE id = ?", (pid,)).fetchone()
        if r is None:
            raise NotFound(pid)
        rows = json.loads(r["items"])
        for row in rows:
            row["view"] = self._view(row)
        return {"id": pid, "kind": r["kind"], "source": json.loads(r["source"]), "skipped": json.loads(r["skipped"]),
                "items": rows, "created": r["created"], "accepted": json.loads(r["accepted"]) if r["accepted"] else None,
                "count": sum(1 for x in rows if not x.get("problem")),
                "card": f"/api/s/calendar/v1/proposals/{pid}"}

    def _view(self, row: dict[str, Any]) -> dict[str, Any]:
        """What the card shows for one proposed item."""
        f = row.get("fields") or {}
        import repeat as R
        return {"title": f.get("title"), "kind": f.get("kind", "event"), "start": f.get("start"), "end": f.get("end"),
                "due": f.get("due"), "all_day": bool(f.get("all_day")),
                "repeat": R.describe(f["rrule"], f.get("start") or f.get("due")) if f.get("rrule") else None,
                "location": f.get("location") or ""}

    def accept(self, pid: str, ids: list[str] | None, calendar: str | None, project_id: str | None,
               origin: dict[str, Any]) -> dict[str, Any]:
        p = self.get(pid)
        if p["accepted"] is not None:
            raise I.Invalid("this proposal was already added", "already_accepted", {"items": p["accepted"]["items"]})
        chosen = [r for r in p["items"] if not r.get("problem") and (ids is None and not r.get("already") or ids is not None and r["pid"] in ids)]
        if not chosen:
            raise I.Invalid("nothing to add: tick at least one item", "nothing_chosen")
        by, src = I.who(origin)
        cal_id = None
        if calendar:
            try:
                cal_id = self.store.find_calendar(calendar)["id"]
            except NotFound:
                raise I.Invalid(f"no calendar {calendar!r}", "unknown_calendar") from None
        made = []
        with self.store.lock:
            for r in chosen:
                f = dict(r["fields"])
                ovs = f.pop("overrides", None) or {}
                f.setdefault("calendar_id", self.store.default_calendar()["id"])
                if cal_id:
                    f["calendar_id"] = cal_id
                if project_id is not None:
                    f["project_id"] = project_id or None
                f["source"] = {**(f.get("source") or {}), "proposal": pid, **({"thread": src.get("thread")} if src.get("thread") else {})}
                f.setdefault("source", {})["kind"] = (f.get("source") or {}).get("kind") or by
                f["touched_by"] = "you"            # you ticked it: it isn't the agent's own test item
                item = self.store.insert(f)
                if ovs:
                    self.store.replace_overrides(item["id"], ovs)
                made.append(item["id"])
            uid = self.store.record_undo([{"id": i, "row": None, "overrides": {}} for i in made])
            self.store.db.execute("UPDATE proposals SET accepted = ? WHERE id = ?",
                                  (json.dumps({"items": made, "at": time.time(), "undo": uid}), pid))
            self.store.bump()
        return {"added": len(made), "items": made, "undo": f"/api/s/calendar/v1/undo/{uid}"}
