"""MemoryStore (plan structured-memory 1.1): entities, aliases, anchors, the change log and undo, in `agent.db`.

Every change is one transaction and one `mem_log` row holding the rows it touched before and after, so any change
can be undone (`undo`) and the Memory page can show an entity's history. Forgetting a fact deletes it for real and
logs only that it happened. Facts are in facts.py (`FactsMixin`). Names resolve without a model: exact name or
alias, compared normalized (`model.norm`).
"""

from __future__ import annotations

import json
import secrets
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from .facts import FactsMixin
from .model import ENTITY_STATES, FOLDERS, KINDS, USER, MemoryError, kind_of, norm

SCHEMA = """
CREATE TABLE IF NOT EXISTS mem_entities (
    id TEXT PRIMARY KEY, kind TEXT NOT NULL, name TEXT NOT NULL, norm TEXT NOT NULL, parent TEXT,
    summary TEXT NOT NULL DEFAULT '', scope TEXT NOT NULL DEFAULT 'user', state TEXT NOT NULL DEFAULT 'active',
    merged_into TEXT, source TEXT NOT NULL DEFAULT 'stated', created REAL NOT NULL, updated REAL NOT NULL);
CREATE INDEX IF NOT EXISTS mem_entities_norm ON mem_entities (norm, state);
CREATE TABLE IF NOT EXISTS mem_aliases (entity TEXT NOT NULL, alias TEXT NOT NULL, norm TEXT NOT NULL, added REAL NOT NULL,
    PRIMARY KEY (entity, norm));
CREATE INDEX IF NOT EXISTS mem_aliases_norm ON mem_aliases (norm);
CREATE TABLE IF NOT EXISTS mem_anchors (entity TEXT NOT NULL, kind TEXT NOT NULL, value TEXT NOT NULL, PRIMARY KEY (kind, value));
CREATE TABLE IF NOT EXISTS mem_facts (
    id TEXT PRIMARY KEY, text TEXT NOT NULL, kind TEXT NOT NULL DEFAULT 'fact', valid_from TEXT, valid_until TEXT,
    recorded REAL NOT NULL, source TEXT NOT NULL, state TEXT NOT NULL, confidence REAL NOT NULL DEFAULT 1,
    replaces TEXT, replaced_by TEXT, evidence TEXT NOT NULL DEFAULT '[]', seen INTEGER NOT NULL DEFAULT 1,
    last_used REAL, updated REAL NOT NULL);
CREATE INDEX IF NOT EXISTS mem_facts_state ON mem_facts (state, updated);
CREATE TABLE IF NOT EXISTS mem_fact_entities (fact TEXT NOT NULL, entity TEXT NOT NULL, PRIMARY KEY (fact, entity));
CREATE INDEX IF NOT EXISTS mem_fact_entities_entity ON mem_fact_entities (entity);
CREATE TABLE IF NOT EXISTS mem_log (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, op TEXT NOT NULL,
    target TEXT NOT NULL, summary TEXT NOT NULL DEFAULT '', before TEXT, after TEXT, by TEXT NOT NULL DEFAULT 'user');
CREATE VIRTUAL TABLE IF NOT EXISTS mem_fts USING fts5(ref UNINDEXED, text, tokenize='porter unicode61');
"""
TABLES = {"mem_entities": "id", "mem_aliases": "entity", "mem_anchors": "entity", "mem_facts": "id",
          "mem_fact_entities": "fact"}
ANCHOR_KINDS = ("workspace", "folder", "git")


def new_id(prefix: str) -> str:
    return prefix + secrets.token_hex(5)


class MemoryStore(FactsMixin):
    def __init__(self, store: Any, clock: Any = time.time) -> None:
        self.c, self.lock, self.clock = store._c, store._lock, clock
        with self.lock:
            self.c.executescript(SCHEMA)
            if not self.c.execute("SELECT 1 FROM mem_entities WHERE id = ?", (USER,)).fetchone():
                now = self.clock()
                self.c.execute("INSERT INTO mem_entities (id, kind, name, norm, created, updated) VALUES (?, 'user', 'You', 'you', ?, ?)",
                               (USER, now, now))

    # ---- plumbing ---------------------------------------------------------------------------------

    @contextmanager
    def tx(self) -> Iterator[None]:
        with self.lock:
            self.c.execute("BEGIN IMMEDIATE")
            try:
                yield
            except BaseException:
                self.c.execute("ROLLBACK")
                raise
            self.c.execute("COMMIT")

    def _rows(self, sql: str, args: Any = ()) -> list[dict[str, Any]]:
        with self.lock:
            return [dict(r) for r in self.c.execute(sql, args).fetchall()]

    def _row(self, sql: str, args: Any = ()) -> dict[str, Any] | None:
        rows = self._rows(sql, args)
        return rows[0] if rows else None

    def snapshot(self, entities: list[str] = (), facts: list[str] = ()) -> dict[str, list[dict[str, Any]]]:   # type: ignore[assignment]
        """The rows that hold these entities and facts, to log and to restore."""
        out: dict[str, list[dict[str, Any]]] = {}
        for table, key in TABLES.items():
            ids = facts if table in ("mem_facts", "mem_fact_entities") else entities
            if table == "mem_fact_entities":
                rows = self._rows(f"SELECT * FROM mem_fact_entities WHERE fact IN ({','.join('?' * len(facts))}) "
                                  f"OR entity IN ({','.join('?' * len(entities))})", [*facts, *entities]) if (facts or entities) else []
            else:
                rows = self._rows(f"SELECT * FROM {table} WHERE {key} IN ({','.join('?' * len(ids))})", list(ids)) if ids else []
            out[table] = rows
        return out

    def _restore(self, snap: dict[str, list[dict[str, Any]]], entities: list[str], facts: list[str]) -> None:
        for table, key in TABLES.items():
            if table == "mem_fact_entities":
                if facts or entities:
                    self.c.execute(f"DELETE FROM mem_fact_entities WHERE fact IN ({','.join('?' * len(facts))}) "
                                   f"OR entity IN ({','.join('?' * len(entities))})", [*facts, *entities])
            else:
                ids = facts if table == "mem_facts" else entities
                if ids:
                    self.c.execute(f"DELETE FROM {table} WHERE {key} IN ({','.join('?' * len(ids))})", list(ids))
            for r in snap.get(table, []):
                self.c.execute(f"INSERT OR REPLACE INTO {table} ({','.join(r)}) VALUES ({','.join('?' * len(r))})", list(r.values()))
        for e in entities:
            self._index_entity(e)
        for f in facts:
            self._index_fact(f)

    def _log(self, op: str, target: str, summary: str, before: Any, after: Any, by: str = "user") -> int:
        cur = self.c.execute("INSERT INTO mem_log (ts, op, target, summary, before, after, by) VALUES (?, ?, ?, ?, ?, ?, ?)",
                             (self.clock(), op, target, summary, json.dumps(before) if before is not None else None,
                              json.dumps(after) if after is not None else None, by))
        return int(cur.lastrowid)

    @contextmanager
    def change(self, op: str, target: str, summary: str, entities: list[str] = (), facts: list[str] = (),  # type: ignore[assignment]
               by: str = "user") -> Iterator[dict[str, Any]]:
        """One logged change: the rows of `entities` and `facts` before and after it (the caller may add ids)."""
        ents, fcts = list(entities), list(facts)
        with self.tx():
            before = self.snapshot(ents, fcts)
            box: dict[str, Any] = {"entities": ents, "facts": fcts}
            yield box
            box["log"] = self._log(op, target, summary, {"ids": {"entities": ents, "facts": fcts}, "rows": before},
                                   {"rows": self.snapshot(ents, fcts)}, by)

    def undo(self, log_id: int, by: str = "user") -> dict[str, Any]:
        r = self._row("SELECT * FROM mem_log WHERE id = ?", (log_id,))
        if r is None or not r["before"]:
            raise MemoryError(404, "not_found", f"no change {log_id} that can be undone")
        if self._row("SELECT id FROM mem_log WHERE op = 'undo' AND target = ?", (str(log_id),)):
            raise MemoryError(409, "undone", f"change {log_id} was already undone")
        before = json.loads(r["before"])
        ids = before["ids"]
        with self.tx():
            now = self.snapshot(ids["entities"], ids["facts"])
            self._restore(before["rows"], ids["entities"], ids["facts"])
            lid = self._log("undo", str(log_id), f"undid: {r['summary']}", {"ids": ids, "rows": now},
                            {"rows": before["rows"]}, by)
        return {"undone": log_id, "log": lid}

    def log(self, target: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        sql = "SELECT id, ts, op, target, summary, by FROM mem_log"
        rows = self._rows(sql + (" WHERE target = ? OR before LIKE ? OR after LIKE ?" if target else "") + " ORDER BY id DESC LIMIT ?",
                          ([target, f'%"{target}"%', f'%"{target}"%'] if target else []) + [limit])
        return rows

    # ---- search index ------------------------------------------------------------------------------

    def _index_entity(self, eid: str) -> None:
        self.c.execute("DELETE FROM mem_fts WHERE ref = ?", (f"entity:{eid}",))
        e = self.c.execute("SELECT * FROM mem_entities WHERE id = ?", (eid,)).fetchone()
        if e is not None and e["state"] == "active":
            aliases = [a[0] for a in self.c.execute("SELECT alias FROM mem_aliases WHERE entity = ?", (eid,))]
            self.c.execute("INSERT INTO mem_fts (ref, text) VALUES (?, ?)", (f"entity:{eid}", " ".join([e["name"], *aliases, e["summary"]])))

    # ---- entities -----------------------------------------------------------------------------------

    def resolve(self, name: str, kind: str | None = None) -> dict[str, Any] | None:
        """An active entity by name or alias, compared normalized; an id or a path works too. Never a model."""
        name = (name or "").strip()
        if not name:
            return None
        e = self._row("SELECT * FROM mem_entities WHERE id = ? AND state = 'active'", (name,))
        if e is None and "/" in name:
            e = self.by_path(name)
        n = norm(name)
        if e is None:
            rows = self._rows("SELECT * FROM mem_entities WHERE norm = ? AND state = 'active'", (n,)) or self._rows(
                "SELECT e.* FROM mem_aliases a JOIN mem_entities e ON e.id = a.entity WHERE a.norm = ? AND e.state = 'active'", (n,))
            rows = [r for r in rows if not kind or r["kind"] == kind] or ([] if kind else rows)
            e = rows[0] if rows else None
        return e

    def by_path(self, path: str) -> dict[str, Any] | None:
        parts = [p for p in path.strip("/").split("/") if p]
        if not parts:
            return None
        kind = kind_of(parts[0]) if parts[0].lower() in FOLDERS.values() or parts[0].lower() in KINDS else None
        if kind == "user" and len(parts) == 1:
            return self.entity_row(USER)
        names, parent = (parts[1:] if kind else parts), None
        e = None
        for nm in names:
            rows = self._rows("SELECT * FROM mem_entities WHERE norm = ? AND state = 'active' AND parent IS ?", (norm(nm), parent))
            rows = [r for r in rows if not kind or parent or r["kind"] == kind]
            if not rows:
                return None
            e, parent = rows[0], rows[0]["id"]
        return e

    def entity_row(self, eid: str) -> dict[str, Any] | None:
        return self._row("SELECT * FROM mem_entities WHERE id = ?", (eid,))

    def need(self, eid: str) -> dict[str, Any]:
        e = self.entity_row(eid) or self.resolve(eid)
        if e is None:
            raise MemoryError(404, "not_found", f"no entity {eid!r}", "GET /v1/memory/tree lists them")
        return e

    def path(self, e: dict[str, Any]) -> str:
        """The kind's folder and the names down to `e` (`projects/GAIFA/agent`); the user is `you`."""
        if e["id"] == USER:
            return "you"
        names, seen, cur, root = [], set(), e, e
        while cur is not None and cur["id"] not in seen:
            seen.add(cur["id"])
            names.append(cur["name"])
            root = cur
            cur = self.entity_row(cur["parent"]) if cur["parent"] else None
        return FOLDERS.get(root["kind"], "topics") + "/" + "/".join(reversed(names))

    def aliases(self, eid: str) -> list[str]:
        return [r["alias"] for r in self._rows("SELECT alias FROM mem_aliases WHERE entity = ? ORDER BY added", (eid,))]

    def anchors(self, eid: str) -> list[dict[str, str]]:
        return self._rows("SELECT kind, value FROM mem_anchors WHERE entity = ? ORDER BY kind, value", (eid,))

    def public(self, e: dict[str, Any]) -> dict[str, Any]:
        return {**{k: e[k] for k in ("id", "kind", "name", "parent", "summary", "scope", "state", "merged_into", "source",
                                     "created", "updated")},
                "path": self.path(e), "aliases": self.aliases(e["id"]), "anchors": self.anchors(e["id"])}

    def _taken(self, n: str, but: str | None = None) -> dict[str, Any] | None:
        """An active entity other than `but` that already answers to the normalized name `n`."""
        r = self._row("SELECT * FROM mem_entities WHERE norm = ? AND state = 'active' AND id IS NOT ?", (n, but))
        return r or self._row("SELECT e.* FROM mem_aliases a JOIN mem_entities e ON e.id = a.entity "
                              "WHERE a.norm = ? AND e.state = 'active' AND e.id IS NOT ?", (n, but))

    def create_entity(self, kind: str, name: str, parent: str | None = None, summary: str = "", aliases: list[str] = (),  # type: ignore[assignment]
                      anchors: list[dict[str, str]] = (), source: str = "stated", state: str = "active",  # type: ignore[assignment]
                      by: str = "user") -> dict[str, Any]:
        kind = kind_of(kind)
        name = (name or "").strip()
        if kind == "user" or not name or not norm(name):
            raise MemoryError(422, "bad_entity", "an entity needs a name and a kind other than user")
        if state not in ENTITY_STATES:
            raise MemoryError(422, "bad_state", f"state is one of {', '.join(ENTITY_STATES)}")
        clash = self._taken(norm(name))
        if clash is not None and state == "active":
            raise MemoryError(409, "exists", f"{name!r} is already {self.path(clash)}", f"use it ({clash['id']}), or add an alias")
        if parent:
            parent = self.need(parent)["id"]
        eid, now = new_id("e_"), self.clock()
        with self.change("entity_create", eid, f"new {kind}: {name}", entities=[eid], by=by):
            self.c.execute("INSERT INTO mem_entities (id, kind, name, norm, parent, summary, state, source, created, updated) "
                           "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (eid, kind, name, norm(name), parent, summary.strip(), state, source, now, now))
            for a in aliases:
                self._add_alias(eid, a)
            for a in anchors:
                self._add_anchor(eid, a.get("kind", ""), a.get("value", ""))
            self._index_entity(eid)
        return self.public(self.need(eid))

    def _add_alias(self, eid: str, alias: str) -> None:
        n = norm(alias)
        if not n or n == self.entity_row(eid)["norm"]:
            return
        clash = self._taken(n, eid)
        if clash is not None:
            raise MemoryError(409, "alias_taken", f"{alias!r} already means {self.path(clash)}")
        self.c.execute("INSERT OR IGNORE INTO mem_aliases (entity, alias, norm, added) VALUES (?, ?, ?, ?)", (eid, alias.strip(), n, self.clock()))

    def _add_anchor(self, eid: str, kind: str, value: str) -> None:
        if kind not in ANCHOR_KINDS or not value.strip():
            raise MemoryError(422, "bad_anchor", f"an anchor is {{kind: {'|'.join(ANCHOR_KINDS)}, value}}")
        other = self._row("SELECT entity FROM mem_anchors WHERE kind = ? AND value = ?", (kind, value.strip()))
        if other and other["entity"] != eid:
            raise MemoryError(409, "anchor_taken", f"{kind}:{value} already belongs to {other['entity']}")
        self.c.execute("INSERT OR IGNORE INTO mem_anchors (entity, kind, value) VALUES (?, ?, ?)", (eid, kind, value.strip()))

    def update_entity(self, eid: str, name: str | None = None, parent: str | None = "", summary: str | None = None,
                      kind: str | None = None, aliases_add: list[str] = (), aliases_remove: list[str] = (),  # type: ignore[assignment]
                      anchors_add: list[dict[str, str]] = (), anchors_remove: list[dict[str, str]] = (),  # type: ignore[assignment]
                      by: str = "user") -> dict[str, Any]:
        """Rename (the old name becomes an alias), move under another parent (`None`: to the top), change the summary,
        kind, aliases or anchors. `parent=""` leaves it where it is."""
        e = self.need(eid)
        eid = e["id"]
        what = []
        with self.change("entity_update", eid, e["name"], entities=[eid], by=by) as box:
            if name is not None and name.strip() and name.strip() != e["name"]:
                clash = self._taken(norm(name), eid)
                if clash is not None:
                    raise MemoryError(409, "exists", f"{name!r} is already {self.path(clash)}", "merge the two instead")
                self.c.execute("DELETE FROM mem_aliases WHERE entity = ? AND norm = ?", (eid, norm(name)))
                self.c.execute("UPDATE mem_entities SET name = ?, norm = ? WHERE id = ?", (name.strip(), norm(name), eid))
                self._add_alias(eid, e["name"])
                what.append(f"renamed {e['name']} → {name.strip()}")
            if parent != "" and eid != USER:
                pid = self.need(parent)["id"] if parent else None
                cur = pid
                while cur:
                    if cur == eid:
                        raise MemoryError(422, "cycle", "an entity can't be inside itself")
                    cur = (self.entity_row(cur) or {}).get("parent")
                self.c.execute("UPDATE mem_entities SET parent = ? WHERE id = ?", (pid, eid))
                what.append("moved")
            if summary is not None:
                self.c.execute("UPDATE mem_entities SET summary = ? WHERE id = ?", (summary.strip(), eid))
                what.append("summary")
            if kind is not None and eid != USER:
                self.c.execute("UPDATE mem_entities SET kind = ? WHERE id = ?", (kind_of(kind), eid))
                what.append(f"kind {kind_of(kind)}")
            for a in aliases_add:
                self._add_alias(eid, a)
            for a in aliases_remove:
                self.c.execute("DELETE FROM mem_aliases WHERE entity = ? AND norm = ?", (eid, norm(a)))
            for a in anchors_add:
                self._add_anchor(eid, a.get("kind", ""), a.get("value", ""))
            for a in anchors_remove:
                self.c.execute("DELETE FROM mem_anchors WHERE entity = ? AND kind = ? AND value = ?", (eid, a.get("kind"), a.get("value")))
            if aliases_add or aliases_remove:
                what.append("aliases")
            if anchors_add or anchors_remove:
                what.append("anchors")
            self.c.execute("UPDATE mem_entities SET updated = ? WHERE id = ?", (self.clock(), eid))
            self._index_entity(eid)
            for f in self._rows("SELECT fact FROM mem_fact_entities WHERE entity = ?", (eid,)):
                self._index_fact(f["fact"])                         # a fact is found by its entities' names too
        with self.lock:
            self.c.execute("UPDATE mem_log SET summary = ? WHERE id = ?", (f"{e['name']}: {', '.join(what) or 'no change'}", box["log"]))
        return self.public(self.need(eid))

    def merge(self, eid: str, into: str, by: str = "user") -> dict[str, Any]:
        """`eid` into `into`: its facts, aliases (and its name), anchors and children move; it becomes `merged`."""
        a, b = self.need(eid), self.need(into)
        if a["id"] == b["id"] or USER in (a["id"],):
            raise MemoryError(422, "bad_merge", "an entity merges into another one, and the user into nothing")
        facts = [r["fact"] for r in self._rows("SELECT fact FROM mem_fact_entities WHERE entity = ?", (a["id"],))]
        kids = [r["id"] for r in self._rows("SELECT id FROM mem_entities WHERE parent = ?", (a["id"],))]
        with self.change("merge", a["id"], f"merged {a['name']} into {b['name']}", entities=[a["id"], b["id"], *kids], facts=facts, by=by):
            for f in facts:
                self.c.execute("INSERT OR IGNORE INTO mem_fact_entities (fact, entity) VALUES (?, ?)", (f, b["id"]))
            self.c.execute("DELETE FROM mem_fact_entities WHERE entity = ?", (a["id"],))
            names = [a["name"], *self.aliases(a["id"])]
            self.c.execute("DELETE FROM mem_aliases WHERE entity = ?", (a["id"],))
            self.c.execute("UPDATE mem_entities SET state = 'merged', merged_into = ?, updated = ? WHERE id = ?", (b["id"], self.clock(), a["id"]))
            for n in names:
                if norm(n) != b["norm"]:
                    self.c.execute("INSERT OR IGNORE INTO mem_aliases (entity, alias, norm, added) VALUES (?, ?, ?, ?)", (b["id"], n, norm(n), self.clock()))
            self.c.execute("UPDATE mem_anchors SET entity = ? WHERE entity = ?", (b["id"], a["id"]))
            self.c.execute("UPDATE mem_entities SET parent = ? WHERE parent = ?", (b["id"], a["id"]))
            for x in (a["id"], b["id"]):
                self._index_entity(x)
            for f in facts:
                self._index_fact(f)
        return self.public(self.need(b["id"]))

    def set_entity_state(self, eid: str, state: str, by: str = "user") -> dict[str, Any]:
        e = self.need(eid) if state != "active" else (self.entity_row(eid) or self.need(eid))
        if state not in ENTITY_STATES or e["id"] == USER:
            raise MemoryError(422, "bad_state", f"state is one of {', '.join(ENTITY_STATES)}")
        if state == "active" and self._taken(e["norm"], e["id"]):
            raise MemoryError(409, "exists", f"another entity is already called {e['name']}", "merge them instead")
        with self.change("entity_state", e["id"], f"{e['name']}: {state}", entities=[e["id"]], by=by):
            self.c.execute("UPDATE mem_entities SET state = ?, updated = ? WHERE id = ?", (state, self.clock(), e["id"]))
            self._index_entity(e["id"])
        return self.public(self.entity_row(e["id"]))   # type: ignore[arg-type]

    def entities(self, kind: str | None = None, state: str = "active") -> list[dict[str, Any]]:
        rows = self._rows("SELECT * FROM mem_entities WHERE state = ?" + (" AND kind = ?" if kind else "") + " ORDER BY name COLLATE NOCASE",
                          (state, kind) if kind else (state,))
        return rows

    def tree(self) -> dict[str, Any]:
        """The kinds, each with its top entities and their children, and how many current facts each holds."""
        counts = {r["entity"]: r["n"] for r in self._rows(
            "SELECT fe.entity, COUNT(*) AS n FROM mem_fact_entities fe JOIN mem_facts f ON f.id = fe.fact "
            "WHERE f.state = 'active' AND (f.valid_until IS NULL OR f.valid_until > ?) GROUP BY fe.entity", (self.today(),))}
        rows = self.entities()
        kids: dict[str | None, list[dict[str, Any]]] = {}
        for r in rows:
            kids.setdefault(r["parent"], []).append(r)
        node = lambda r: {"id": r["id"], "name": r["name"], "kind": r["kind"], "facts": counts.get(r["id"], 0),  # noqa: E731
                          "children": [node(k) for k in kids.get(r["id"], [])]}
        out = []
        for kind in KINDS:
            top = [node(r) for r in kids.get(None, []) if r["kind"] == kind]
            if top or kind in ("user", "project"):
                out.append({"kind": kind, "folder": FOLDERS[kind], "entities": top})
        return {"kinds": out, "proposed": len(self.entities(state="proposed")) + self.count_facts("proposed")}
