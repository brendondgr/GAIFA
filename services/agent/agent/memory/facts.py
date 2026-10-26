"""The facts (plan structured-memory 1.1), mixed into MemoryStore.

A fact is about one or more entities (by id; names and paths resolve, and an unknown name becomes a new topic, or
the kind given with it). The same sentence about the same entities again only counts as seen once more. A fact is
never overwritten: `replaces` retires the old one (its `valid_until` and `replaced_by` set) and keeps it as history.
A proposed fact (what the agent learned on its own) does nothing until the user approves it; approving one that
replaces another retires that one then.
"""

from __future__ import annotations

import json
import re
from typing import Any

from .model import FACT_KINDS, FACT_STATES, SOURCES, USER, MemoryError, check_date, kind_of, norm, today

MAX_TEXT = 1000
STOP = frozenset("""a an and are as at be but by can could did do does for from had has have he her his how i if in into is it
its me my no not of on or our she so than that the their them then there these they this to too us was we were what when
where which who why will with would you your yours i'm im it's don't dont about just please also any some""".split())


class FactsMixin:
    c: Any
    lock: Any
    clock: Any

    def today(self) -> str:
        return today()

    def _current_sql(self, alias: str = "f") -> str:
        return f"{alias}.state = 'active' AND ({alias}.valid_until IS NULL OR {alias}.valid_until > '{self.today()}')"

    def _index_fact(self, fid: str) -> None:
        self._mark(f"fact:{fid}")   # type: ignore[attr-defined]
        self.c.execute("DELETE FROM mem_fts WHERE ref = ?", (f"fact:{fid}",))
        f = self.c.execute(f"SELECT * FROM mem_facts f WHERE id = ? AND {self._current_sql()}", (fid,)).fetchone()
        if f is not None:
            names = [r[0] for r in self.c.execute("SELECT e.name FROM mem_fact_entities fe JOIN mem_entities e ON e.id = fe.entity "
                                                  "WHERE fe.fact = ?", (fid,))]
            self.c.execute("INSERT INTO mem_fts (ref, text) VALUES (?, ?)", (f"fact:{fid}", " ".join([f["text"], *names])))

    def count_facts(self, state: str) -> int:
        with self.lock:
            return int(self.c.execute("SELECT COUNT(*) FROM mem_facts WHERE state = ?", (state,)).fetchone()[0])

    def fact_row(self, fid: str) -> dict[str, Any] | None:
        return self._row("SELECT * FROM mem_facts WHERE id = ?", (fid,))   # type: ignore[attr-defined]

    def need_fact(self, fid: str) -> dict[str, Any]:
        f = self.fact_row(fid)
        if f is None:
            raise MemoryError(404, "not_found", f"no fact {fid!r}")
        return f

    def fact_public(self, f: dict[str, Any]) -> dict[str, Any]:
        ents = self._rows("SELECT e.* FROM mem_fact_entities fe JOIN mem_entities e ON e.id = fe.entity WHERE fe.fact = ? "   # type: ignore[attr-defined]
                          "ORDER BY e.kind = 'user', e.name", (f["id"],))
        current = f["state"] == "active" and (not f["valid_until"] or f["valid_until"] > self.today())
        return {**{k: f[k] for k in ("id", "text", "kind", "valid_from", "valid_until", "recorded", "source", "state",
                                     "confidence", "replaces", "replaced_by", "seen", "last_used", "updated")},
                "evidence": json.loads(f["evidence"] or "[]"), "current": current,
                "entities": [{"id": e["id"], "name": e["name"], "kind": e["kind"], "path": self.path(e)} for e in ents]}   # type: ignore[attr-defined]

    def facts(self, state: str | None = None, entity: str | None = None, q: str | None = None, current: bool | None = None,
              limit: int = 200) -> list[dict[str, Any]]:
        where, args = [], []
        if state:
            where.append("f.state = ?")
            args.append(state)
        if current:
            where.append(self._current_sql())
        if entity:
            where.append("f.id IN (SELECT fact FROM mem_fact_entities WHERE entity = ?)")
            args.append(self.need(entity)["id"])   # type: ignore[attr-defined]
        if q:
            where.append("f.text LIKE ?")
            args.append(f"%{q}%")
        rows = self._rows("SELECT * FROM mem_facts f" + (" WHERE " + " AND ".join(where) if where else "")   # type: ignore[attr-defined]
                          + " ORDER BY f.updated DESC LIMIT ?", [*args, limit])
        return [self.fact_public(r) for r in rows]

    def facts_of(self, eid: str, current: bool = True) -> list[dict[str, Any]]:
        return self.facts(entity=eid, current=current or None, limit=1000)

    def resolve_about(self, about: list[Any] | None, source: str, by: str) -> list[str]:
        """Entity ids for `about`: ids, paths and names resolve; an unknown name becomes a new entity (`{name, kind}`
        gives its kind, a path's first part too; plain text a topic), proposed when the fact is inferred. Paths and
        kinds go first, a bare name that repeats one is the same entry, and an entry of another kind by that name is
        used rather than refused. Nothing: the user."""
        items: list[tuple[str, str | None]] = []
        for a in about or []:
            name, kind = (a.get("name"), a.get("kind")) if isinstance(a, dict) else (str(a), None)
            if (name or "").strip():
                items.append((name.strip().strip("/"), kind))
        items.sort(key=lambda x: ("/" not in x[0] and not x[1]))           # paths and kinds first
        ids: list[str] = []
        for name, kind in items:
            if norm(name) in ("you", "me", "user", "the user", "your"):
                ids.append(USER)
                continue
            parts = [p for p in name.split("/") if p]
            leaf = parts[-1]
            if len(parts) == 1 and any(norm(leaf) == (self.entity_row(i) or {}).get("norm") for i in ids):   # type: ignore[attr-defined]
                continue                                                  # "Ariadne" after "projects/Ariadne"
            want = kind_of(kind) if kind else (kind_of(parts[0]) if len(parts) == 2 else None)
            e = self.resolve(name, want) or self.resolve(name) or (self.resolve(leaf, want) if len(parts) > 1 else None)   # type: ignore[attr-defined]
            if e is None and len(parts) > 1:
                e = self.resolve(leaf) if len(parts) == 2 else None   # type: ignore[attr-defined]
            if e is None:
                parent = None
                if len(parts) > 2:                          # projects/GAIFA/agent: under its parent
                    pe = self.resolve("/".join(parts[:-1]))   # type: ignore[attr-defined]
                    parent = pe["id"] if pe else None
                    want = want or (pe or {}).get("kind")
                e = self.create_entity(want or "topic", leaf, parent=parent, source=source, by=by,   # type: ignore[attr-defined]
                                       state="proposed" if source == "inferred" else "active")
            ids.append(e["id"])
        return list(dict.fromkeys(ids)) or [USER]

    def add_fact(self, text: str, about: list[Any] | None = None, kind: str = "fact", valid_from: str | None = None,
                 valid_until: str | None = None, source: str = "stated", state: str | None = None,
                 evidence: list[dict[str, Any]] | None = None, confidence: float = 1.0, replaces: str | None = None,
                 by: str = "user") -> dict[str, Any]:
        text = re.sub(r"\s+", " ", text or "").strip()
        if not text or len(text) > MAX_TEXT:
            raise MemoryError(422, "bad_fact", f"a fact is one sentence of 1–{MAX_TEXT} characters")
        if kind not in FACT_KINDS or source not in SOURCES:
            raise MemoryError(422, "bad_fact", f"kind is one of {', '.join(FACT_KINDS)}; source one of {', '.join(SOURCES)}")
        state = state or ("proposed" if source == "inferred" else "active")
        if state not in FACT_STATES:
            raise MemoryError(422, "bad_state", f"state is one of {', '.join(FACT_STATES)}")
        valid_from, valid_until = check_date(valid_from, "valid_from"), check_date(valid_until, "valid_until")
        old = self.need_fact(replaces) if replaces else None
        if old is not None and old["state"] not in ("active", "proposed"):
            raise MemoryError(409, "not_current", f"{replaces} is {old['state']}: only a current fact can be replaced")
        ents = self.resolve_about(about, source, by)
        same = self._same(text, ents)
        if same is not None and old is not None and same["id"] != old["id"]:   # saved already; now it replaces `old`
            with self.change("fact_replace", same["id"], f"replaced: {old['text'][:60]} → {text[:60]}",   # type: ignore[attr-defined]
                             facts=[same["id"], old["id"]], by=by):
                self.c.execute("UPDATE mem_facts SET replaces = ? WHERE id = ?", (old["id"], same["id"]))
                if same["state"] == "active":
                    self._retire_for(old["id"], same["id"], same["valid_from"])
            return self.fact_public(self.need_fact(same["id"]))
        if same is not None and not replaces:                 # said again: seen once more, with the new evidence
            with self.change("fact_seen", same["id"], f"seen again: {text[:80]}", facts=[same["id"]], by=by):   # type: ignore[attr-defined]
                ev = json.loads(same["evidence"] or "[]") + list(evidence or [])
                self.c.execute("UPDATE mem_facts SET seen = seen + 1, evidence = ?, updated = ? WHERE id = ?",
                               (json.dumps(ev[-20:]), self.clock(), same["id"]))
            return self.fact_public(self.need_fact(same["id"]))
        from .store import new_id
        fid, now = new_id("f_"), self.clock()
        with self.change("fact_add", fid, (f"replaced: {old['text'][:60]} → " if old else "") + text[:80],   # type: ignore[attr-defined]
                         entities=[], facts=[fid, *([old["id"]] if old else [])], by=by):
            self.c.execute("INSERT INTO mem_facts (id, text, kind, valid_from, valid_until, recorded, source, state, confidence, "
                           "replaces, evidence, updated) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                           (fid, text, kind, valid_from, valid_until, now, source, state, confidence, replaces,
                            json.dumps(list(evidence or [])[-20:]), now))
            for e in ents:
                self.c.execute("INSERT OR IGNORE INTO mem_fact_entities (fact, entity) VALUES (?, ?)", (fid, e))
            if old is not None and state == "active":
                self._retire_for(old["id"], fid, valid_from)
            self._index_fact(fid)
        return self.fact_public(self.need_fact(fid))

    def _same(self, text: str, ents: list[str]) -> dict[str, Any] | None:
        n = norm(text)
        for f in self._rows(f"SELECT * FROM mem_facts f WHERE state IN ('active', 'proposed') AND id IN "   # type: ignore[attr-defined]
                            f"(SELECT fact FROM mem_fact_entities WHERE entity = ?)", (ents[0],)):
            if norm(f["text"]) == n and {r["entity"] for r in self._rows("SELECT entity FROM mem_fact_entities WHERE fact = ?", (f["id"],))} == set(ents):   # type: ignore[attr-defined]
                return f
        return None

    def _retire_for(self, old: str, new: str, valid_from: str | None) -> None:
        self.c.execute("UPDATE mem_facts SET state = 'retired', valid_until = COALESCE(valid_until, ?), replaced_by = ?, updated = ? "
                       "WHERE id = ?", (valid_from or self.today(), new, self.clock(), old))
        self._index_fact(old)

    def update_fact(self, fid: str, text: str | None = None, about: list[Any] | None = None, kind: str | None = None,
                    valid_from: str | None = "", valid_until: str | None = "", by: str = "user") -> dict[str, Any]:
        """Correct a fact in place (the user's own edit; the log keeps what it said). `""` leaves a date as it is."""
        f = self.need_fact(fid)
        with self.change("fact_update", fid, f"edited: {(text or f['text'])[:80]}", facts=[fid], by=by):   # type: ignore[attr-defined]
            if text is not None:
                t = re.sub(r"\s+", " ", text).strip()
                if not t or len(t) > MAX_TEXT:
                    raise MemoryError(422, "bad_fact", f"a fact is one sentence of 1–{MAX_TEXT} characters")
                self.c.execute("UPDATE mem_facts SET text = ? WHERE id = ?", (t, fid))
            if kind is not None:
                if kind not in FACT_KINDS:
                    raise MemoryError(422, "bad_fact", f"kind is one of {', '.join(FACT_KINDS)}")
                self.c.execute("UPDATE mem_facts SET kind = ? WHERE id = ?", (kind, fid))
            if valid_from != "":
                self.c.execute("UPDATE mem_facts SET valid_from = ? WHERE id = ?", (check_date(valid_from, "valid_from"), fid))
            if valid_until != "":
                self.c.execute("UPDATE mem_facts SET valid_until = ? WHERE id = ?", (check_date(valid_until, "valid_until"), fid))
            if about is not None:
                ents = self.resolve_about(about, f["source"], by)
                self.c.execute("DELETE FROM mem_fact_entities WHERE fact = ?", (fid,))
                for e in ents:
                    self.c.execute("INSERT INTO mem_fact_entities (fact, entity) VALUES (?, ?)", (fid, e))
            self.c.execute("UPDATE mem_facts SET updated = ? WHERE id = ?", (self.clock(), fid))
            self._index_fact(fid)
        return self.fact_public(self.need_fact(fid))

    def set_fact_state(self, fid: str, state: str, by: str = "user") -> dict[str, Any]:
        """approve (proposed → active, retiring what it replaces), reject, retire, or bring back (active)."""
        f = self.need_fact(fid)
        if state not in FACT_STATES:
            raise MemoryError(422, "bad_state", f"state is one of {', '.join(FACT_STATES)}")
        facts = [fid, *([f["replaces"]] if f["replaces"] else [])]
        ents = [r["entity"] for r in self._rows("SELECT entity FROM mem_fact_entities WHERE fact = ?", (fid,))]   # type: ignore[attr-defined]
        proposed_ents = [e for e in ents if (self.entity_row(e) or {}).get("state") == "proposed"]   # type: ignore[attr-defined]
        with self.change("fact_" + state, fid, f"{state}: {f['text'][:80]}", entities=proposed_ents, facts=facts, by=by):   # type: ignore[attr-defined]
            self.c.execute("UPDATE mem_facts SET state = ?, updated = ?" + (", valid_until = COALESCE(valid_until, ?)" if state == "retired" else "")
                           + " WHERE id = ?", (state, self.clock(), *([self.today()] if state == "retired" else []), fid))
            if state == "active" and f["state"] == "proposed":
                if f["replaces"] and (self.fact_row(f["replaces"]) or {}).get("state") == "active":
                    self._retire_for(f["replaces"], fid, f["valid_from"])
                for e in proposed_ents:                        # a new entity the fact brought comes with it
                    self.c.execute("UPDATE mem_entities SET state = 'active' WHERE id = ?", (e,))
                    self._index_entity(e)   # type: ignore[attr-defined]
            if state == "active" and f["state"] == "retired":
                self.c.execute("UPDATE mem_facts SET valid_until = NULL, replaced_by = NULL WHERE id = ?", (fid,))
            self._index_fact(fid)
        return self.fact_public(self.need_fact(fid))

    def forget(self, fid: str, by: str = "user") -> dict[str, Any]:
        """Delete a fact for real: the log keeps only that one was forgotten, not what it said."""
        f = self.need_fact(fid)
        with self.tx():   # type: ignore[attr-defined]
            self._scrub(fid, f["text"])
            self.c.execute("DELETE FROM mem_fact_entities WHERE fact = ?", (fid,))
            self.c.execute("DELETE FROM mem_facts WHERE id = ?", (fid,))
            self.c.execute("DELETE FROM mem_fts WHERE ref = ?", (f"fact:{fid}",))
            self._mark(f"fact:{fid}")   # type: ignore[attr-defined]
            self.c.execute("UPDATE mem_facts SET replaces = NULL WHERE replaces = ?", (fid,))
            self.c.execute("UPDATE mem_facts SET replaced_by = NULL WHERE replaced_by = ?", (fid,))
            self._log("forget", fid, "a fact was forgotten", None, None, by)   # type: ignore[attr-defined]
        return {"forgotten": fid}

    def _scrub(self, fid: str, text: str) -> None:
        """Take a forgotten fact out of the log: its rows in every change, and its words in every summary.
        Those changes can still be undone; the fact doesn't come back with them."""
        rows = self.c.execute("SELECT id, summary, before, after FROM mem_log WHERE target = ? OR before LIKE ? OR after LIKE ? "
                              "OR summary LIKE ?", (fid, f"%{fid}%", f"%{fid}%", f"%{text[:60]}%")).fetchall()
        for r in rows:
            out = []
            for col in ("before", "after"):
                d = json.loads(r[col]) if r[col] else None
                if d:
                    rows_ = d.get("rows", {})
                    rows_["mem_facts"] = [x for x in rows_.get("mem_facts", []) if x.get("id") != fid]
                    rows_["mem_fact_entities"] = [x for x in rows_.get("mem_fact_entities", []) if x.get("fact") != fid]
                    if "ids" in d:
                        d["ids"]["facts"] = [x for x in d["ids"]["facts"] if x != fid]
                out.append(json.dumps(d) if d is not None else None)
            summary = r["summary"].replace(text[:80], "(a forgotten fact)").replace(text[:60], "(a forgotten fact)")
            self.c.execute("UPDATE mem_log SET summary = ?, before = ?, after = ? WHERE id = ?", (summary, *out, r["id"]))

    def touch(self, ids: list[str]) -> None:
        if ids:
            with self.lock:
                self.c.execute(f"UPDATE mem_facts SET last_used = ? WHERE id IN ({','.join('?' * len(ids))})", [self.clock(), *ids])

    def keyword(self, q: str, limit: int = 30) -> list[tuple[str, float]]:
        """FTS5 over current facts and active entities: [(ref, score)], best first. `ref` is fact:<id> or entity:<id>."""
        words = [w for w in re.findall(r"[^\W_]+", (q or "").lower()) if len(w) > 1 and w not in STOP][:24]
        if not words:
            return []
        match = " OR ".join(f'"{w}"' for w in words)
        with self.lock:
            rows = self.c.execute("SELECT ref, bm25(mem_fts) AS s FROM mem_fts WHERE mem_fts MATCH ? ORDER BY s LIMIT ?", (match, limit)).fetchall()
        return [(r["ref"], -float(r["s"])) for r in rows]
