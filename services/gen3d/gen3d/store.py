"""Persistent state: chats, jobs and stage timings in SQLite; job outputs in data/jobs/<id>/.

Everything is small and fast, so one connection guarded by a lock is plenty (the GPU is the
bottleneck by five orders of magnitude).
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import threading
import time
import uuid
from pathlib import Path

from .config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS chats (
    id TEXT PRIMARY KEY, title TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY, chat_id TEXT, parent_id TEXT, title TEXT,
    status TEXT NOT NULL,                  -- queued | running | done | failed | canceled
    request TEXT NOT NULL,                 -- JobRequest JSON
    input_mesh TEXT,                       -- uploaded mesh (relative to the job dir) if any
    stages TEXT NOT NULL DEFAULT '{}',     -- {stage: {state, step, total, started, finished, seconds, eta_s, note}}
    result TEXT NOT NULL DEFAULT '{}',     -- stage outputs: faces, parts, files...
    error TEXT,
    created REAL NOT NULL, started REAL, finished REAL
);
CREATE INDEX IF NOT EXISTS jobs_chat ON jobs(chat_id, created);
CREATE INDEX IF NOT EXISTS jobs_status ON jobs(status, created);
CREATE TABLE IF NOT EXISTS timings (
    id INTEGER PRIMARY KEY AUTOINCREMENT, stage TEXT NOT NULL, features TEXT NOT NULL,
    seconds REAL NOT NULL, created REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS timings_stage ON timings(stage, id);
"""

JSON_COLS = ("request", "stages", "result")
TERMINAL = ("done", "failed", "canceled")


def new_id(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:10]}"


class Store:
    def __init__(self, db_path: Path | None = None, jobs_dir: Path | None = None):
        self.db_path = db_path or settings.db_path
        self.jobs_dir = jobs_dir or settings.jobs_dir
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.db_path, check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(SCHEMA)
        self._lock = threading.Lock()

    def _q(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._db.execute(sql, args).fetchall()

    # ---- chats --------------------------------------------------------------------------------

    def create_chat(self, title: str = "New chat") -> dict:
        now = time.time()
        cid = new_id("c_")
        self._q("INSERT INTO chats VALUES (?,?,?,?)", (cid, title.strip()[:120] or "New chat", now, now))
        return self.get_chat(cid)

    def get_chat(self, cid: str) -> dict | None:
        rows = self._q("SELECT * FROM chats WHERE id=?", (cid,))
        return dict(rows[0]) if rows else None

    def list_chats(self) -> list[dict]:
        rows = self._q("""SELECT c.*, COUNT(j.id) AS jobs,
                            SUM(j.status IN ('queued','running')) AS active
                          FROM chats c LEFT JOIN jobs j ON j.chat_id = c.id
                          GROUP BY c.id ORDER BY c.updated DESC""")
        return [{**dict(r), "active": r["active"] or 0} for r in rows]

    def update_chat(self, cid: str, title: str | None = None) -> dict | None:
        if title is not None:
            self._q("UPDATE chats SET title=?, updated=? WHERE id=?", (title.strip()[:120] or "New chat", time.time(), cid))
        return self.get_chat(cid)

    def touch_chat(self, cid: str) -> None:
        self._q("UPDATE chats SET updated=? WHERE id=?", (time.time(), cid))

    def delete_chat(self, cid: str) -> list[str]:
        ids = [r["id"] for r in self._q("SELECT id FROM jobs WHERE chat_id=?", (cid,))]
        for jid in ids:
            self.delete_job(jid)
        self._q("DELETE FROM chats WHERE id=?", (cid,))
        return ids

    # ---- jobs ---------------------------------------------------------------------------------

    def job_dir(self, jid: str) -> Path:
        return self.jobs_dir / jid

    def create_job(self, request: dict, *, chat_id: str | None, parent_id: str | None,
                   title: str | None, stages: list[str], jid: str | None = None) -> dict:
        jid = jid or new_id("j_")
        self.job_dir(jid).mkdir(parents=True, exist_ok=True)
        st = {s: {"state": "pending"} for s in stages}
        self._q("""INSERT INTO jobs (id, chat_id, parent_id, title, status, request, stages, created)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (jid, chat_id, parent_id, title, "queued", json.dumps(request), json.dumps(st), time.time()))
        if chat_id:
            self.touch_chat(chat_id)
        return self.get_job(jid)

    def _row(self, r: sqlite3.Row) -> dict:
        d = dict(r)
        for c in JSON_COLS:
            d[c] = json.loads(d[c]) if d[c] else {}
        return d

    def get_job(self, jid: str) -> dict | None:
        rows = self._q("SELECT * FROM jobs WHERE id=?", (jid,))
        return self._row(rows[0]) if rows else None

    def list_jobs(self, chat_id: str | None = None, status: str | None = None, limit: int = 200) -> list[dict]:
        sql, args = "SELECT * FROM jobs WHERE 1=1", []
        if chat_id:
            sql += " AND chat_id=?"; args.append(chat_id)
        if status:
            sql += " AND status IN (%s)" % ",".join("?" * len(status.split(","))); args += status.split(",")
        sql += " ORDER BY created DESC LIMIT ?"; args.append(limit)
        return [self._row(r) for r in self._q(sql, tuple(args))]

    def queued(self) -> list[dict]:
        return [self._row(r) for r in self._q("SELECT * FROM jobs WHERE status='queued' ORDER BY created")]

    def update_job(self, jid: str, **fields) -> dict | None:
        if not fields:
            return self.get_job(jid)
        cols, args = [], []
        for k, v in fields.items():
            cols.append(f"{k}=?")
            args.append(json.dumps(v) if k in JSON_COLS else v)
        self._q(f"UPDATE jobs SET {', '.join(cols)} WHERE id=?", (*args, jid))
        return self.get_job(jid)

    def delete_job(self, jid: str) -> bool:
        shutil.rmtree(self.job_dir(jid), ignore_errors=True)  # permanent, never the desktop Trash
        return bool(self._q("DELETE FROM jobs WHERE id=? RETURNING id", (jid,)))

    def requeue_interrupted(self) -> list[str]:
        """Jobs left 'running' by a stopped server go back to the front of the queue."""
        ids = [r["id"] for r in self._q("SELECT id FROM jobs WHERE status='running'")]
        for jid in ids:
            job = self.get_job(jid)
            stages = {s: ({"state": "pending"} if v.get("state") != "done" else v) for s, v in job["stages"].items()}
            self.update_job(jid, status="queued", stages=stages, started=None,
                            error=None)
        return ids

    # ---- timings (ETA learning) ---------------------------------------------------------------

    def add_timing(self, stage: str, features: dict, seconds: float) -> None:
        self._q("INSERT INTO timings (stage, features, seconds, created) VALUES (?,?,?,?)",
                (stage, json.dumps(features, sort_keys=True), float(seconds), time.time()))

    def timings(self, stage: str, limit: int = 200) -> list[dict]:
        rows = self._q("SELECT features, seconds FROM timings WHERE stage=? ORDER BY id DESC LIMIT ?", (stage, limit))
        return [{"features": json.loads(r["features"]), "seconds": r["seconds"]} for r in rows]

    def close(self) -> None:
        self._db.close()
