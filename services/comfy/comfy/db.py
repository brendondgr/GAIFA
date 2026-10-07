"""comfy.db: runs (one per queued workflow), and the per-task default packs."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,            -- the adapter's job id
    prompt_id TEXT,                 -- ComfyUI's
    workflow TEXT NOT NULL,
    label TEXT,
    state TEXT NOT NULL,            -- queued | running | done | failed | cancelled
    progress REAL,
    inputs TEXT,                    -- resolved inputs (JSON)
    outputs TEXT,                   -- [{path, kind}] (JSON)
    error TEXT,
    created REAL NOT NULL,
    started REAL,
    finished REAL,
    peak_gb REAL
);
CREATE INDEX IF NOT EXISTS runs_workflow ON runs(workflow, finished);
CREATE TABLE IF NOT EXISTS defaults (task TEXT PRIMARY KEY, workflow TEXT NOT NULL);
"""
JSON_COLS = ("inputs", "outputs")


class DB:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._c = sqlite3.connect(path, check_same_thread=False)
        self._c.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._c.execute("PRAGMA journal_mode=WAL")
            self._c.executescript(SCHEMA)

    def close(self) -> None:
        self._c.close()

    def _row(self, r: sqlite3.Row | None) -> dict | None:
        if r is None:
            return None
        d = dict(r)
        for k in JSON_COLS:
            d[k] = json.loads(d[k]) if d[k] else None
        return d

    def add_run(self, run_id: str, workflow: str, label: str, inputs: dict) -> None:
        with self._lock, self._c:
            self._c.execute("INSERT INTO runs (id, workflow, label, state, inputs, created) VALUES (?,?,?,?,?,?)",
                            (run_id, workflow, label, "queued", json.dumps(inputs), time.time()))

    def update_run(self, run_id: str, **fields) -> None:
        if not fields:
            return
        vals = [json.dumps(v) if k in JSON_COLS and v is not None else v for k, v in fields.items()]
        with self._lock, self._c:
            self._c.execute(f"UPDATE runs SET {', '.join(f'{k}=?' for k in fields)} WHERE id=?", (*vals, run_id))

    def run(self, run_id: str) -> dict | None:
        with self._lock:
            return self._row(self._c.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone())

    def runs(self, states: tuple[str, ...] = (), workflow: str | None = None, since: float = 0, limit: int = 100) -> list[dict]:
        q, args = "SELECT * FROM runs WHERE created >= ?", [since]
        if states:
            q += f" AND state IN ({','.join('?' * len(states))})"
            args += states
        if workflow:
            q += " AND workflow = ?"
            args.append(workflow)
        q += " ORDER BY created DESC LIMIT ?"
        args.append(limit)
        with self._lock:
            return [self._row(r) for r in self._c.execute(q, args).fetchall()]

    def peak_gb(self, workflow: str) -> float | None:
        """The typical peak memory of this workflow: the median over its last 10 finished runs (a run
        measured while another workflow's models were still loaded mustn't inflate it for good)."""
        with self._lock:
            rows = [r[0] for r in self._c.execute("SELECT peak_gb FROM runs WHERE workflow=? AND state='done' "
                                                  "AND peak_gb IS NOT NULL ORDER BY finished DESC LIMIT 10", (workflow,))]
        if not rows:
            return None
        rows.sort()
        mid = len(rows) // 2
        return rows[mid] if len(rows) % 2 else (rows[mid - 1] + rows[mid]) / 2

    def defaults(self) -> dict[str, str]:
        with self._lock:
            return {r["task"]: r["workflow"] for r in self._c.execute("SELECT * FROM defaults")}

    def set_default(self, task: str, workflow: str | None) -> None:
        with self._lock, self._c:
            if workflow:
                self._c.execute("INSERT INTO defaults VALUES (?,?) ON CONFLICT(task) DO UPDATE SET workflow=excluded.workflow",
                                (task, workflow))
            else:
                self._c.execute("DELETE FROM defaults WHERE task=?", (task,))
