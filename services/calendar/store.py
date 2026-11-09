"""The calendar's store (calendar plan 1.2): calendars, items (events and to-dos), overrides of one occurrence,
fired alerts, proposals and undo records, in one SQLite file (`CALENDAR_DB`).

Every write bumps `rev` (the page and the agent's agenda cache follow it) and can record what it changed as an
undo: the rows of each touched item (and its overrides) as they were before, restored as a whole.
"""

from __future__ import annotations

import json
import secrets
import sqlite3
import threading
import time
from collections.abc import Iterable
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS calendars (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, color TEXT NOT NULL, is_default INTEGER NOT NULL DEFAULT 0,
  hidden INTEGER NOT NULL DEFAULT 0, position INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS items (
  id TEXT PRIMARY KEY, calendar_id TEXT NOT NULL, kind TEXT NOT NULL, title TEXT NOT NULL, notes TEXT NOT NULL DEFAULT '',
  location TEXT NOT NULL DEFAULT '', url TEXT NOT NULL DEFAULT '', start TEXT, "end" TEXT, all_day INTEGER NOT NULL DEFAULT 0,
  tz TEXT NOT NULL, due TEXT, done_at REAL, priority INTEGER NOT NULL DEFAULT 0, estimate_min INTEGER,
  busy TEXT NOT NULL DEFAULT 'busy', rrule TEXT, exdates TEXT NOT NULL DEFAULT '[]', project_id TEXT,
  alerts TEXT NOT NULL DEFAULT '[]', prep TEXT, source TEXT NOT NULL DEFAULT '{}', touched_by TEXT NOT NULL DEFAULT 'you',
  created REAL NOT NULL, updated REAL NOT NULL, deleted_at REAL);
CREATE INDEX IF NOT EXISTS items_cal ON items(calendar_id);
CREATE INDEX IF NOT EXISTS items_project ON items(project_id);
CREATE TABLE IF NOT EXISTS overrides (
  item_id TEXT NOT NULL, occurrence TEXT NOT NULL, fields TEXT NOT NULL DEFAULT '{}', cancelled INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (item_id, occurrence));
CREATE TABLE IF NOT EXISTS fired (
  id TEXT PRIMARY KEY, item_id TEXT NOT NULL, occurrence TEXT NOT NULL, alert_at REAL NOT NULL, fired_at REAL NOT NULL,
  state TEXT NOT NULL DEFAULT 'unread', snooze_until REAL, late INTEGER NOT NULL DEFAULT 0, title TEXT NOT NULL DEFAULT '',
  body TEXT NOT NULL DEFAULT '', kind TEXT NOT NULL DEFAULT 'event', before_min INTEGER NOT NULL DEFAULT 0,
  posted INTEGER NOT NULL DEFAULT 0, ts REAL);
CREATE UNIQUE INDEX IF NOT EXISTS fired_once ON fired(item_id, occurrence, before_min);
CREATE TABLE IF NOT EXISTS proposals (
  id TEXT PRIMARY KEY, kind TEXT NOT NULL, items TEXT NOT NULL, source TEXT NOT NULL DEFAULT '{}', skipped TEXT NOT NULL DEFAULT '[]',
  created REAL NOT NULL, accepted TEXT);
CREATE TABLE IF NOT EXISTS undo (id TEXT PRIMARY KEY, ops TEXT NOT NULL, created REAL NOT NULL, done INTEGER NOT NULL DEFAULT 0);
"""

PALETTE = ["#4F7CFF", "#2BB673", "#F2994A", "#E5484D", "#9B6CFF", "#14B8C4", "#D6409F", "#8A94A6"]
JSON_COLS = {"exdates": [], "alerts": [], "prep": None, "source": {}}
ITEM_COLS = ("calendar_id", "kind", "title", "notes", "location", "url", "start", "end", "all_day", "tz", "due",
             "done_at", "priority", "estimate_min", "busy", "rrule", "exdates", "project_id", "alerts", "prep",
             "source", "touched_by")
TRASH_DAYS = 30


class NotFound(KeyError):
    pass


def new_id(prefix: str, n: int = 5) -> str:
    return f"{prefix}_{secrets.token_hex(n)}"


def _row(r: sqlite3.Row | None) -> dict[str, Any] | None:
    if r is None:
        return None
    d = dict(r)
    for k, empty in JSON_COLS.items():
        if k in d:
            d[k] = json.loads(d[k]) if d[k] else empty
    for k in ("fields",):
        if k in d:
            d[k] = json.loads(d[k] or "{}")
    if "all_day" in d:
        d["all_day"] = bool(d["all_day"])
    return d


def _dump(k: str, v: Any) -> Any:
    if k in JSON_COLS:
        return None if v is None and JSON_COLS[k] is None else json.dumps(v if v is not None else JSON_COLS[k])
    if k == "all_day":
        return 1 if v else 0
    return v


class Store:
    def __init__(self, path: str) -> None:
        self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.lock = threading.RLock()
        self.db.executescript(SCHEMA)
        if not self.db.execute("SELECT 1 FROM calendars LIMIT 1").fetchone():
            self.add_calendar("Personal", PALETTE[0], is_default=True)

    # ---- the revision ------------------------------------------------------------------------------------------
    @property
    def rev(self) -> int:
        r = self.db.execute("SELECT value FROM meta WHERE key='rev'").fetchone()
        return int(r[0]) if r else 0

    def bump(self) -> None:
        self.db.execute("INSERT INTO meta(key, value) VALUES('rev', '1') "
                        "ON CONFLICT(key) DO UPDATE SET value = CAST(value AS INTEGER) + 1")

    # ---- calendars ---------------------------------------------------------------------------------------------
    def calendars(self) -> list[dict[str, Any]]:
        rows = self.db.execute("SELECT * FROM calendars ORDER BY position, created").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["is_default"], d["hidden"] = bool(d["is_default"]), bool(d["hidden"])
            out.append(d)
        return out

    def calendar(self, cid: str) -> dict[str, Any]:
        for c in self.calendars():
            if c["id"] == cid:
                return c
        raise NotFound(cid)

    def default_calendar(self) -> dict[str, Any]:
        cals = self.calendars()
        return next((c for c in cals if c["is_default"]), cals[0])

    def find_calendar(self, ref: str | None) -> dict[str, Any]:
        """A calendar by id or by name (any case); None → the default."""
        if not ref:
            return self.default_calendar()
        for c in self.calendars():
            if c["id"] == ref or c["name"].lower() == ref.strip().lower():
                return c
        raise NotFound(ref)

    def add_calendar(self, name: str, color: str | None = None, is_default: bool = False) -> dict[str, Any]:
        with self.lock:
            n = self.db.execute("SELECT COUNT(*) FROM calendars").fetchone()[0]
            cid = new_id("cal", 4)
            self.db.execute("INSERT INTO calendars(id, name, color, is_default, hidden, position, created) VALUES (?,?,?,?,0,?,?)",
                            (cid, name.strip()[:60] or "Calendar", color or PALETTE[n % len(PALETTE)], 0, n, time.time()))
            if is_default:
                self._set_default(cid)
            self.bump()
            return self.calendar(cid)

    def _set_default(self, cid: str) -> None:
        self.db.execute("UPDATE calendars SET is_default = (id = ?)", (cid,))

    def patch_calendar(self, cid: str, fields: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            self.calendar(cid)
            for k in ("name", "color", "hidden", "position"):
                if k in fields and fields[k] is not None:
                    v = fields[k]
                    v = (1 if v else 0) if k == "hidden" else v
                    self.db.execute(f"UPDATE calendars SET {k} = ? WHERE id = ?", (v, cid))
            if fields.get("is_default"):
                self._set_default(cid)
            self.bump()
            return self.calendar(cid)

    def delete_calendar(self, cid: str, items: str) -> dict[str, Any]:
        """`items`: `move:<calendar id>` or `trash`. The last calendar can't go."""
        with self.lock:
            cal = self.calendar(cid)
            others = [c for c in self.calendars() if c["id"] != cid]
            if not others:
                raise ValueError("the last calendar can't be deleted")
            ids = [r[0] for r in self.db.execute("SELECT id FROM items WHERE calendar_id = ? AND deleted_at IS NULL", (cid,))]
            if items.startswith("move:"):
                to = self.calendar(items[5:])["id"]
                if to == cid:
                    raise ValueError("move the items to another calendar")
                self.db.execute("UPDATE items SET calendar_id = ? WHERE calendar_id = ?", (to, cid))
            elif items == "trash":
                now = time.time()
                self.db.execute("UPDATE items SET deleted_at = ?, calendar_id = ? WHERE calendar_id = ? AND deleted_at IS NULL",
                                (now, others[0]["id"], cid))
            elif ids:
                raise ValueError("the calendar has items: move them (items=move:<id>) or trash them (items=trash)")
            self.db.execute("DELETE FROM calendars WHERE id = ?", (cid,))
            if cal["is_default"]:
                self._set_default(others[0]["id"])
            self.bump()
            return {"deleted": cid, "items": len(ids)}

    # ---- items -------------------------------------------------------------------------------------------------
    def get(self, iid: str, trashed: bool = False) -> dict[str, Any]:
        r = _row(self.db.execute("SELECT * FROM items WHERE id = ?", (iid,)).fetchone())
        if r is None or (r["deleted_at"] is not None and not trashed):
            raise NotFound(iid)
        return r

    def items(self, ids: Iterable[str] | None = None, calendars: list[str] | None = None,
              kinds: list[str] | None = None, project: str | None = None) -> list[dict[str, Any]]:
        sql, args = "SELECT * FROM items WHERE deleted_at IS NULL", []
        if ids is not None:
            ids = list(ids)
            sql += f" AND id IN ({','.join('?' * len(ids))})" if ids else " AND 0"
            args += ids
        if calendars:
            sql += f" AND calendar_id IN ({','.join('?' * len(calendars))})"
            args += calendars
        if kinds:
            sql += f" AND kind IN ({','.join('?' * len(kinds))})"
            args += kinds
        if project:
            sql += " AND project_id = ?"
            args.append(project)
        return [_row(r) for r in self.db.execute(sql, args).fetchall()]  # type: ignore[misc]

    def overrides(self, iid: str) -> dict[str, dict[str, Any]]:
        rows = self.db.execute("SELECT * FROM overrides WHERE item_id = ?", (iid,)).fetchall()
        return {r["occurrence"]: {"fields": json.loads(r["fields"] or "{}"), "cancelled": bool(r["cancelled"])} for r in rows}

    def all_overrides(self, ids: list[str]) -> dict[str, dict[str, dict[str, Any]]]:
        out: dict[str, dict[str, dict[str, Any]]] = {i: {} for i in ids}
        if not ids:
            return out
        for r in self.db.execute(f"SELECT * FROM overrides WHERE item_id IN ({','.join('?' * len(ids))})", ids):
            out.setdefault(r["item_id"], {})[r["occurrence"]] = {"fields": json.loads(r["fields"] or "{}"),
                                                                 "cancelled": bool(r["cancelled"])}
        return out

    def insert(self, fields: dict[str, Any], iid: str | None = None) -> dict[str, Any]:
        now = time.time()
        iid = iid or new_id("c")
        row = {k: _dump(k, fields.get(k)) for k in ITEM_COLS}
        row["exdates"] = row["exdates"] or "[]"
        row["alerts"] = row["alerts"] or "[]"
        row["source"] = row["source"] or "{}"
        row["touched_by"] = fields.get("touched_by") or "you"
        row["busy"] = fields.get("busy") or "busy"
        row["priority"] = fields.get("priority") or 0
        for k in ("notes", "location", "url"):
            row[k] = fields.get(k) or ""
        row["all_day"] = 1 if fields.get("all_day") else 0
        cols = ", ".join(f'"{k}"' for k in row)
        self.db.execute(f"INSERT INTO items(id, {cols}, created, updated) VALUES (?, {', '.join('?' * len(row))}, ?, ?)",
                        (iid, *row.values(), now, now))
        return self.get(iid)

    def update(self, iid: str, fields: dict[str, Any]) -> dict[str, Any]:
        sets = {k: _dump(k, v) for k, v in fields.items() if k in ITEM_COLS or k == "deleted_at"}
        if sets:
            sets["updated"] = time.time()
            self.db.execute(f"UPDATE items SET {', '.join(f'{chr(34)}{k}{chr(34)} = ?' for k in sets)} WHERE id = ?",
                            (*sets.values(), iid))
        return self.get(iid, trashed=True)

    def set_override(self, iid: str, occ: str, fields: dict[str, Any] | None = None, cancelled: bool | None = None) -> None:
        cur = self.overrides(iid).get(occ) or {"fields": {}, "cancelled": False}
        f = {**cur["fields"], **(fields or {})}
        c = cur["cancelled"] if cancelled is None else cancelled
        self.db.execute("INSERT INTO overrides(item_id, occurrence, fields, cancelled) VALUES (?,?,?,?) "
                        "ON CONFLICT(item_id, occurrence) DO UPDATE SET fields = excluded.fields, cancelled = excluded.cancelled",
                        (iid, occ, json.dumps(f), 1 if c else 0))

    def replace_overrides(self, iid: str, ovs: dict[str, dict[str, Any]]) -> None:
        self.db.execute("DELETE FROM overrides WHERE item_id = ?", (iid,))
        for occ, o in ovs.items():
            self.db.execute("INSERT INTO overrides(item_id, occurrence, fields, cancelled) VALUES (?,?,?,?)",
                            (iid, occ, json.dumps(o.get("fields") or {}), 1 if o.get("cancelled") else 0))

    def search(self, q: str, limit: int = 30) -> list[dict[str, Any]]:
        like = f"%{q.strip()}%"
        rows = self.db.execute("SELECT * FROM items WHERE deleted_at IS NULL AND (title LIKE ? OR notes LIKE ? OR location LIKE ?) "
                               "ORDER BY COALESCE(start, due, '') DESC LIMIT ?", (like, like, like, limit)).fetchall()
        return [_row(r) for r in rows]  # type: ignore[misc]

    def trash(self) -> list[dict[str, Any]]:
        rows = self.db.execute("SELECT * FROM items WHERE deleted_at IS NOT NULL ORDER BY deleted_at DESC").fetchall()
        return [_row(r) for r in rows]  # type: ignore[misc]

    def purge(self, older_than: float | None = None) -> int:
        cut = older_than if older_than is not None else time.time() - TRASH_DAYS * 86400
        with self.lock:
            ids = [r[0] for r in self.db.execute("SELECT id FROM items WHERE deleted_at IS NOT NULL AND deleted_at < ?", (cut,))]
            for i in ids:
                self.db.execute("DELETE FROM overrides WHERE item_id = ?", (i,))
                self.db.execute("DELETE FROM fired WHERE item_id = ?", (i,))
                self.db.execute("DELETE FROM items WHERE id = ?", (i,))
            if ids:
                self.bump()
            return len(ids)

    # ---- undo --------------------------------------------------------------------------------------------------
    def snapshot(self, ids: Iterable[str]) -> list[dict[str, Any]]:
        """The rows of these items (None: not there yet) and their overrides, for an undo record."""
        out = []
        for i in ids:
            r = self.db.execute("SELECT * FROM items WHERE id = ?", (i,)).fetchone()
            out.append({"id": i, "row": dict(r) if r else None, "overrides": self.overrides(i)})
        return out

    def record_undo(self, snaps: list[dict[str, Any]]) -> str:
        uid = new_id("u")
        self.db.execute("INSERT INTO undo(id, ops, created) VALUES (?,?,?)", (uid, json.dumps(snaps), time.time()))
        self.db.execute("DELETE FROM undo WHERE created < ?", (time.time() - 7 * 86400,))
        return uid

    def undo(self, uid: str) -> list[str]:
        """Puts each item of the record back as it was. A second undo of the same record does nothing."""
        with self.lock:
            r = self.db.execute("SELECT ops, done FROM undo WHERE id = ?", (uid,)).fetchone()
            if r is None:
                raise NotFound(uid)
            if r["done"]:
                return []
            snaps = json.loads(r["ops"])
            for s in snaps:
                self.db.execute("DELETE FROM items WHERE id = ?", (s["id"],))
                if s["row"]:
                    row = s["row"]
                    cols = ", ".join(f'"{k}"' for k in row)
                    self.db.execute(f"INSERT INTO items({cols}) VALUES ({', '.join('?' * len(row))})", tuple(row.values()))
                self.replace_overrides(s["id"], s["overrides"])
            self.db.execute("UPDATE undo SET done = 1 WHERE id = ?", (uid,))
            self.bump()
            return [s["id"] for s in snaps]
