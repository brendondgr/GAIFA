"""Turn records (plan 21.4): one row per turn in agent.db's `turns`, written when a turn ends.

What a turn did, for the Learning page and the learner: model, harness version, steps, tokens,
tool calls, errors, card edits and denials, and how it ended. Rebuilt from the event log, so a
row can always be made again.
"""

from __future__ import annotations

from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS turns (
    thread_id TEXT NOT NULL, turn INTEGER NOT NULL, started REAL NOT NULL, ended REAL, model TEXT,
    harness_version INTEGER, steps INTEGER NOT NULL DEFAULT 0, prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0, tool_calls INTEGER NOT NULL DEFAULT 0, errors INTEGER NOT NULL DEFAULT 0,
    edits INTEGER NOT NULL DEFAULT 0, denials INTEGER NOT NULL DEFAULT 0, outcome TEXT,
    PRIMARY KEY (thread_id, turn)
);
"""


def summarize(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The thread's events → one record per turn (a turn starts at a user message or a button's call)."""
    turns: list[dict[str, Any]] = []
    cur: dict[str, Any] | None = None
    edited: set[str] = set()
    for e in events:
        t, p = e["type"], e.get("payload") or {}
        if t == "user" or (t == "tool_call" and p.get("by") == "user"):
            cur = {"turn": len(turns) + 1, "started": e["ts"], "ended": e["ts"], "model": None, "harness_version": None,
                   "steps": 0, "prompt_tokens": 0, "completion_tokens": 0, "tool_calls": 0, "errors": 0, "edits": 0,
                   "denials": 0, "outcome": None}
            turns.append(cur)
        if cur is None:
            continue
        cur["ended"] = e["ts"]
        if t == "usage":
            cur["steps"] += 1
            cur["prompt_tokens"] += int(p.get("prompt_tokens") or 0)
            cur["completion_tokens"] += int(p.get("completion_tokens") or 0)
            cur["model"] = p.get("model") or cur["model"]
            cur["harness_version"] = p.get("harness") if p.get("harness") is not None else cur["harness_version"]
        elif t == "tool_call":
            cur["tool_calls"] += 1
        elif t == "tool_result" and p.get("status") == "error":
            cur["errors"] += 1
        elif t == "decision":
            if not p.get("approve"):
                cur["denials"] += 1
            elif p.get("arguments") and p.get("id") not in edited:
                edited.add(p.get("id"))
                cur["edits"] += 1
        elif t == "error":
            cur["errors"] += 1
        elif t == "state" and p.get("state") in ("idle", "error", "waiting"):
            cur["outcome"] = {"idle": "done", "error": "error", "waiting": "waiting"}[p["state"]]
    return turns


def record(store: Any, tid: str) -> int:
    """Rewrite the thread's turn rows from its events; returns how many turns it has."""
    rows = summarize(store.events(tid))
    with store._lock:
        store._c.execute("BEGIN")
        store._c.execute("DELETE FROM turns WHERE thread_id = ?", (tid,))
        store._c.executemany(
            "INSERT INTO turns (thread_id, turn, started, ended, model, harness_version, steps, prompt_tokens, completion_tokens, "
            "tool_calls, errors, edits, denials, outcome) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [(tid, r["turn"], r["started"], r["ended"], r["model"], r["harness_version"], r["steps"], r["prompt_tokens"],
              r["completion_tokens"], r["tool_calls"], r["errors"], r["edits"], r["denials"], r["outcome"]) for r in rows])
        store._c.execute("COMMIT")
    return len(rows)


def turns(store: Any, tid: str) -> list[dict[str, Any]]:
    with store._lock:
        cur = store._c.execute("SELECT * FROM turns WHERE thread_id = ? ORDER BY turn", (tid,))
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]
