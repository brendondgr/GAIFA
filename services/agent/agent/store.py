"""Threads and their event log (plan 14.4): `agent.db`.

A thread is an append-only list of events; the model's messages are rebuilt from it (context.py).
Event types (payload fields):

    user            {text, attachments?, queued?}
    thinking        {text, seconds, step}
    assistant       {text, step}
    tool_call       {id, name, arguments, step, by: "model" | "user"}
    tool_result     {id, name, status, content, outputs?, call_id?, error?}
    question        {id, questions}                      (an ask_user call waiting for answers)
    answer          {id, answers}
    feedback        {value: up|down, note, output_id? | seq?}   (thumbs, plan 21.4)
    proposal        {prefs: [{id, scope, tool, field, value, when, cue}]}   (the miner's proposals, plan 21.5)
    approval        {id, approval_id, tool, arguments, ask_fields, schema, risk, description, filled?}   (filled: the hub chose these, plan 20.4)
    decision        {id, approval_id, approve, arguments?, reason?}
    todos           {items: [{text, state}]}
    memory          {text, topic}
    compact         {stage: "clear" | "summary", summary?, upto_seq?, cleared?: [seq]}
    usage           {prompt_tokens, completion_tokens, model, used, window}
    note            {text, level}                        (fallback model used, step limit, …)
    error           {code, detail, fix?}
    state           {state: idle | running | waiting | cancelled | error, reason?}

Fork copies the events up to a seq into a new thread (rewind and branch).
"""

from __future__ import annotations

import json
import secrets
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS threads (
    id        TEXT PRIMARY KEY,
    title     TEXT NOT NULL DEFAULT '',
    model     TEXT,
    mode      TEXT NOT NULL DEFAULT 'ask',
    state     TEXT NOT NULL DEFAULT 'idle',
    settings  TEXT NOT NULL DEFAULT '{}',
    created   REAL NOT NULL,
    updated   REAL NOT NULL,
    archived  INTEGER NOT NULL DEFAULT 0,
    parent_id TEXT,
    fork_seq  INTEGER
);
CREATE INDEX IF NOT EXISTS threads_updated ON threads (archived, updated DESC);
CREATE TABLE IF NOT EXISTS events (
    thread_id TEXT NOT NULL,
    seq       INTEGER NOT NULL,
    ts        REAL NOT NULL,
    type      TEXT NOT NULL,
    payload   TEXT NOT NULL,
    tokens    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (thread_id, seq)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS events_type ON events (type, ts);
"""
MODES = ("ask", "auto", "read_only")


def new_id(prefix: str) -> str:
    return prefix + secrets.token_hex(6)


class Store:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._c = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._c.row_factory = sqlite3.Row
        self._c.execute("PRAGMA journal_mode=WAL")
        self._c.execute("PRAGMA busy_timeout=5000")
        self._lock = threading.RLock()   # one connection, shared by FastAPI's worker threads: every use goes through it
        self._c.executescript(SCHEMA)
        from .records import SCHEMA as TURNS            # plan 21.4: one row per turn
        self._c.executescript(TURNS)

    def close(self) -> None:
        with self._lock:
            self._c.close()

    def _all(self, sql: str, args: Any = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._c.execute(sql, args).fetchall()

    def _one(self, sql: str, args: Any = ()) -> Any:
        with self._lock:
            return self._c.execute(sql, args).fetchone()

    # ---- threads ---------------------------------------------------------------------------

    def _thread(self, r: sqlite3.Row | None) -> dict[str, Any] | None:
        if r is None:
            return None
        t = dict(r)
        t["settings"] = json.loads(t["settings"] or "{}")
        t["archived"] = bool(t["archived"])
        return t

    def create_thread(self, title: str = "", model: str | None = None, mode: str = "ask",
                      settings: dict[str, Any] | None = None, parent_id: str | None = None,
                      fork_seq: int | None = None) -> dict[str, Any]:
        tid, now = new_id("t_"), time.time()
        with self._lock:
            self._c.execute("INSERT INTO threads (id, title, model, mode, settings, created, updated, parent_id, fork_seq) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            (tid, title, model, mode if mode in MODES else "ask", json.dumps(settings or {}), now, now,
                             parent_id, fork_seq))
        return self.thread(tid)  # type: ignore[return-value]

    def thread(self, tid: str) -> dict[str, Any] | None:
        return self._thread(self._one("SELECT * FROM threads WHERE id = ?", (tid,)))

    def threads(self, q: str | None = None, archived: bool = False, limit: int = 200) -> list[dict[str, Any]]:
        sql, args = "SELECT * FROM threads WHERE archived = ?", [int(archived)]
        if q:
            sql += (" AND (title LIKE ? OR id IN (SELECT thread_id FROM events WHERE type IN ('user', 'assistant') "
                    "AND payload LIKE ?))")
            args += [f"%{q}%", f"%{q}%"]
        sql += " ORDER BY updated DESC LIMIT ?"
        args.append(limit)
        return [self._thread(r) for r in self._all(sql, args)]  # type: ignore[misc]

    def update_thread(self, tid: str, **fields: Any) -> dict[str, Any] | None:
        allowed = {"title", "model", "mode", "state", "settings", "archived"}
        sets, args = [], []
        for k, v in fields.items():
            if k not in allowed or v is None:
                continue
            if k == "settings":
                v = json.dumps(v)
            if k == "archived":
                v = int(bool(v))
            sets.append(f"{k} = ?")
            args.append(v)
        if sets:
            sets.append("updated = ?")
            args += [time.time(), tid]
            with self._lock:
                self._c.execute(f"UPDATE threads SET {', '.join(sets)} WHERE id = ?", args)
        return self.thread(tid)

    def events_by_type(self, types: list[str], since: float = 0) -> list[dict[str, Any]]:
        """Events of these types in every real chat (not eval dry runs, not chats that opted out of
        learning), oldest first, each with its thread id (plan 21.5)."""
        marks = ", ".join("?" * len(types))
        rows = self._all(f"SELECT e.thread_id, e.seq, e.ts, e.type, e.payload FROM events e JOIN threads t ON t.id = e.thread_id "
                         f"WHERE e.type IN ({marks}) AND e.ts >= ? AND json_extract(t.settings, '$.dry_run') IS NULL "
                         f"AND COALESCE(json_extract(t.settings, '$.no_learn'), 0) = 0 ORDER BY e.ts", [*types, since])
        return [{"thread_id": r["thread_id"], "seq": r["seq"], "ts": r["ts"], "type": r["type"], "payload": json.loads(r["payload"])}
                for r in rows]

    def prune_dry_runs(self, days: float = 30, now: float | None = None) -> int:
        """Archived eval threads (`settings.dry_run`) older than `days` (plan 21.1); real chats are kept."""
        cutoff = (now or time.time()) - days * 86400
        with self._lock:
            ids = [r[0] for r in self._c.execute(
                "SELECT id FROM threads WHERE archived = 1 AND json_extract(settings, '$.dry_run') IS NOT NULL AND updated < ?",
                (cutoff,)).fetchall()]
        return sum(self.delete_thread(t) for t in ids)

    def delete_thread(self, tid: str) -> bool:
        with self._lock:
            self._c.execute("BEGIN")
            self._c.execute("DELETE FROM events WHERE thread_id = ?", (tid,))
            n = self._c.execute("DELETE FROM threads WHERE id = ?", (tid,)).rowcount
            self._c.execute("COMMIT")
        return bool(n)

    # ---- events ----------------------------------------------------------------------------

    def append(self, tid: str, type_: str, payload: dict[str, Any], tokens: int = 0) -> dict[str, Any]:
        now = time.time()
        with self._lock:
            self._c.execute("BEGIN IMMEDIATE")
            try:
                seq = (self._c.execute("SELECT COALESCE(MAX(seq), 0) FROM events WHERE thread_id = ?", (tid,)).fetchone()[0]) + 1
                self._c.execute("INSERT INTO events (thread_id, seq, ts, type, payload, tokens) VALUES (?, ?, ?, ?, ?, ?)",
                                (tid, seq, now, type_, json.dumps(payload, ensure_ascii=False, default=str), tokens))
                self._c.execute("UPDATE threads SET updated = ? WHERE id = ?", (now, tid))
                self._c.execute("COMMIT")
            except BaseException:
                self._c.execute("ROLLBACK")
                raise
        return {"thread_id": tid, "seq": seq, "ts": now, "type": type_, "payload": payload}

    def events(self, tid: str, after: int = 0, upto: int | None = None, types: tuple[str, ...] = ()) -> list[dict[str, Any]]:
        sql, args = "SELECT * FROM events WHERE thread_id = ? AND seq > ?", [tid, after]
        if upto is not None:
            sql += " AND seq <= ?"
            args.append(upto)
        if types:
            sql += f" AND type IN ({','.join('?' * len(types))})"
            args += list(types)
        sql += " ORDER BY seq"
        return [{"thread_id": r["thread_id"], "seq": r["seq"], "ts": r["ts"], "type": r["type"],
                 "payload": json.loads(r["payload"])} for r in self._all(sql, args)]

    def event(self, tid: str, seq: int) -> dict[str, Any] | None:
        evs = self.events(tid, seq - 1, seq)
        return evs[0] if evs else None

    def last_seq(self, tid: str) -> int:
        return self._one("SELECT COALESCE(MAX(seq), 0) FROM events WHERE thread_id = ?", (tid,))[0]

    def fork(self, tid: str, seq: int) -> dict[str, Any]:
        src = self.thread(tid)
        if src is None:
            raise KeyError(tid)
        events = self.events(tid, 0, seq)
        events = trim_unresolved(events)
        title = (src["title"] or "Chat") + " (branch)"
        new = self.create_thread(title, src["model"], src["mode"], src["settings"], parent_id=tid, fork_seq=seq)
        with self._lock:
            self._c.execute("BEGIN")
            for i, e in enumerate(events, 1):
                self._c.execute("INSERT INTO events (thread_id, seq, ts, type, payload, tokens) VALUES (?, ?, ?, ?, ?, 0)",
                                (new["id"], i, e["ts"], e["type"], json.dumps(e["payload"], ensure_ascii=False, default=str)))
            self._c.execute("COMMIT")
        return new

    # ---- stats -----------------------------------------------------------------------------

    def stats(self, since: float) -> dict[str, int]:
        threads = self._one("SELECT COUNT(*) FROM threads WHERE archived = 0")[0]
        msgs = self._one("SELECT COUNT(*) FROM events WHERE type = 'user' AND ts >= ?", (since,))[0]
        toks = 0
        for (p,) in self._all("SELECT payload FROM events WHERE type = 'usage' AND ts >= ?", (since,)):
            u = json.loads(p)
            toks += int(u.get("prompt_tokens") or 0) + int(u.get("completion_tokens") or 0)
        return {"threads": threads, "messages": msgs, "tokens": toks}

    def per_day(self, since: float) -> list[tuple[float, int]]:
        rows = self._all("SELECT ts FROM events WHERE type = 'user' AND ts >= ?", (since,))
        return [(r[0], 1) for r in rows]


def trim_unresolved(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A fork never ends inside a pending step: tool calls without results (and their questions
    and approvals) at the end are dropped."""
    resolved = {e["payload"]["id"] for e in events if e["type"] == "tool_result"}
    out = list(events)
    while out:
        last = out[-1]
        pid = last["payload"].get("id") if isinstance(last["payload"], dict) else None
        if last["type"] in ("tool_call", "question", "approval", "decision", "answer") and pid not in resolved:
            out.pop()
        elif last["type"] in ("state", "usage", "thinking") :
            out.pop()
        else:
            break
    return out
