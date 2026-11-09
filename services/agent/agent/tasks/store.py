"""TaskStore (plan scheduled-tasks 1.2): scheduled tasks, their runs and their notes, in `agent.db`.

A task is `{id, name, instructions, project_id, schedule, enabled, model, mode, skills, allow, settings, own_env, only_own,
use_profile, use_project_memory, keep_days, next_due, created, updated}`:
- `schedule`: tasks/when.py's shape; `next_due` the next time it runs (null while off);
- `allow`: the pre-allows, `{tools: [globs], sites: [hosts | "*"], mcp: [servers]}`, written as the run chat's grants;
- `settings`: the chat's tool groups (`disabled`, `pinned`, `mcp_on`);
- `own_env`: the hidden workspace environment with its own folders; `only_own`: a project task uses only those.

A run is one chat (`thread_id`) the task started: `queued` → `running` → `done` | `failed`, or `skipped` (with `why`);
`late` counts the missed runs it stands in for, `refused` the calls refused because no one was there, `judge` what the
judge's health check found, `seen` whether you opened it. A note is a line on how to do the task, kept by its runs.
A chat belongs to a task through `threads.settings.task` (store.TASK_OF).
"""

from __future__ import annotations

import json
import secrets
import time
from typing import Any

from . import when

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id                 TEXT PRIMARY KEY,
    name               TEXT NOT NULL,
    instructions       TEXT NOT NULL DEFAULT '',
    project_id         TEXT,
    schedule           TEXT NOT NULL,
    enabled            INTEGER NOT NULL DEFAULT 1,
    model              TEXT,
    mode               TEXT NOT NULL DEFAULT 'auto',
    skills             TEXT NOT NULL DEFAULT '[]',
    allow              TEXT NOT NULL DEFAULT '{}',
    settings           TEXT NOT NULL DEFAULT '{}',
    own_env            TEXT,
    only_own           INTEGER NOT NULL DEFAULT 0,
    use_profile        INTEGER NOT NULL DEFAULT 1,
    use_project_memory INTEGER NOT NULL DEFAULT 1,
    keep_days          INTEGER NOT NULL DEFAULT 30,
    next_due           REAL,
    created            REAL NOT NULL,
    updated            REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS task_runs (
    id        TEXT PRIMARY KEY,
    task_id   TEXT NOT NULL,
    thread_id TEXT,
    due       REAL NOT NULL,
    started   REAL,
    ended     REAL,
    state     TEXT NOT NULL DEFAULT 'queued',
    why       TEXT NOT NULL DEFAULT '',
    late      INTEGER NOT NULL DEFAULT 0,
    test      INTEGER NOT NULL DEFAULT 0,
    refused   INTEGER NOT NULL DEFAULT 0,
    judge     TEXT,
    seen      INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS task_runs_task ON task_runs (task_id, due DESC);
CREATE INDEX IF NOT EXISTS task_runs_thread ON task_runs (thread_id);
CREATE TABLE IF NOT EXISTS task_notes (
    id        TEXT PRIMARY KEY,
    task_id   TEXT NOT NULL,
    text      TEXT NOT NULL,
    thread_id TEXT,
    added     REAL NOT NULL,
    updated   REAL NOT NULL
);
"""
NAME_MAX = 120
INSTRUCTIONS_MAX = 16_000
MODES = ("plan", "accept_edits", "auto", "bypass")      # Manual asks every time: nothing for a run with no one there
STATES = ("queued", "running", "done", "failed", "skipped")
NOTES_MAX, NOTE_CHARS = 20, 500
ALLOW_KEYS = ("tools", "sites", "mcp")
SETTING_KEYS = ("disabled", "pinned", "mcp_on")
BOOLS = ("enabled", "only_own", "use_profile", "use_project_memory")
JSONS = ("schedule", "skills", "allow", "settings")


class TaskError(Exception):
    def __init__(self, code: str, detail: str, status: int = 422) -> None:
        super().__init__(detail)
        self.code, self.detail, self.status = code, detail, status


def new_id(prefix: str) -> str:
    return prefix + secrets.token_hex(5)


def _strs(v: Any, most: int = 64, cut: int = 200) -> list[str]:
    out: list[str] = []
    for x in v if isinstance(v, list) else []:
        x = str(x).strip()[:cut]
        if x and x not in out:
            out.append(x)
    return out[:most]


def clean_allow(a: Any) -> dict[str, list[str]]:
    a = a if isinstance(a, dict) else {}
    out = {k: _strs(a.get(k)) for k in ALLOW_KEYS}
    out["sites"] = [s.lower().rstrip(".") if s != "*" else s for s in out["sites"]]
    return out


def clean_settings(s: Any) -> dict[str, list[str]]:
    s = s if isinstance(s, dict) else {}
    return {k: _strs(s[k]) for k in SETTING_KEYS if k in s}


class TaskStore:
    def __init__(self, store: Any, clock: Any = time.time) -> None:
        self.c, self.lock, self.clock = store._c, store._lock, clock
        with self.lock:
            self.c.executescript(SCHEMA)

    def _rows(self, sql: str, args: Any = ()) -> list[dict[str, Any]]:
        with self.lock:
            return [dict(r) for r in self.c.execute(sql, args).fetchall()]

    @staticmethod
    def _task(r: dict[str, Any] | None) -> dict[str, Any] | None:
        if r is None:
            return None
        t = dict(r)
        for k in JSONS:
            t[k] = json.loads(t.get(k) or ("[]" if k == "skills" else "{}"))
        for k in BOOLS:
            t[k] = bool(t.get(k))
        t["when"] = when.describe(t["schedule"])
        return t

    # ---- tasks ------------------------------------------------------------------------------------

    def _fields(self, fields: dict[str, Any]) -> dict[str, Any]:
        """The columns these fields set, checked."""
        out: dict[str, Any] = {}
        for k, v in fields.items():
            if k == "name":
                v = " ".join(str(v or "").split())
                if not v:
                    raise TaskError("bad_name", "a task needs a name")
                if len(v) > NAME_MAX:
                    raise TaskError("bad_name", f"a task's name is at most {NAME_MAX} characters")
            elif k == "instructions":
                v = str(v or "")
                if len(v) > INSTRUCTIONS_MAX:
                    raise TaskError("too_long", f"the instructions are at most {INSTRUCTIONS_MAX:,} characters")
            elif k == "schedule":
                problems = when.check(v)
                if problems:
                    raise TaskError("invalid_schedule", "; ".join(problems))
                v = json.dumps(v)
            elif k == "mode":
                v = {"read_only": "plan"}.get(str(v), str(v))
                if v not in MODES:
                    raise TaskError("bad_mode", f"a task's mode is one of {', '.join(MODES)} (Manual asks every time, "
                                    "and no one is there to answer)")
            elif k == "skills":
                v = json.dumps(_strs(v, 32))
            elif k == "allow":
                v = json.dumps(clean_allow(v))
            elif k == "settings":
                v = json.dumps(clean_settings(v))
            elif k in BOOLS:
                v = int(bool(v))
            elif k == "keep_days":
                if not isinstance(v, int) or isinstance(v, bool) or not 1 <= v <= 3650:
                    raise TaskError("bad_keep_days", "keep_days is 1 to 3650")
            elif k in ("model", "project_id", "own_env"):
                v = str(v)[:200] if v else None
            elif k == "next_due":
                v = float(v) if v is not None else None
            else:
                continue
            out[k] = v
        return out

    def create(self, name: str, schedule: dict[str, Any], **fields: Any) -> dict[str, Any]:
        cols = self._fields({"name": name, "schedule": schedule, **fields})
        tid, now = new_id("k_"), self.clock()
        if "next_due" not in cols:
            cols["next_due"] = when.next_after(schedule, now) if cols.get("enabled", 1) else None
        cols.update(id=tid, created=now, updated=now)
        with self.lock:
            self.c.execute(f"INSERT INTO tasks ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", list(cols.values()))
        return self.get(tid)  # type: ignore[return-value]

    def get(self, tid: str) -> dict[str, Any] | None:
        rows = self._rows(f"SELECT k.*, {_LAST} AS last_run, {_UNREAD} AS unread FROM tasks k WHERE k.id = ?", (tid,))
        return self._with_last(self._task(rows[0] if rows else None))

    def _with_last(self, t: dict[str, Any] | None) -> dict[str, Any] | None:
        if t is not None:
            t["last_run"] = self.run(t["last_run"]) if t.get("last_run") else None
        return t

    def list(self, q: str | None = None, project: str | None = None) -> list[dict[str, Any]]:
        """On first, then by the next run; `q` searches names and instructions; `project` only that project's
        (`none`: the standalone ones)."""
        sql, args = f"SELECT k.*, {_LAST} AS last_run, {_UNREAD} AS unread FROM tasks k WHERE 1", []
        if q:
            sql += " AND (k.name LIKE ? OR k.instructions LIKE ?)"
            args += [f"%{q}%", f"%{q}%"]
        if project == "none":
            sql += " AND k.project_id IS NULL"
        elif project:
            sql += " AND k.project_id = ?"
            args.append(project)
        sql += " ORDER BY k.enabled DESC, COALESCE(k.next_due, 1e18), lower(k.name)"
        return [self._with_last(self._task(r)) for r in self._rows(sql, args)]  # type: ignore[misc]

    def update(self, tid: str, **fields: Any) -> dict[str, Any] | None:
        """`next_due` follows: recomputed from now when the schedule changes or the task is turned on, cleared when
        it's turned off."""
        old = self.get(tid)
        if old is None:
            return None
        cols = self._fields(fields)
        if not cols:
            return old
        enabled = bool(cols.get("enabled", old["enabled"]))
        if "next_due" not in cols and ("schedule" in cols or "enabled" in cols):
            sched = json.loads(cols["schedule"]) if "schedule" in cols else old["schedule"]
            if not enabled:
                cols["next_due"] = None
            elif "schedule" in cols or not old["enabled"] or old["next_due"] is None:
                cols["next_due"] = when.next_after(sched, self.clock())
        if set(cols) != {"next_due"}:
            cols["updated"] = self.clock()
        with self.lock:
            self.c.execute(f"UPDATE tasks SET {', '.join(f'{k} = ?' for k in cols)} WHERE id = ?", [*cols.values(), tid])
        return self.get(tid)

    def delete(self, tid: str) -> bool:
        """The task, its runs and notes; its chats are left to the caller (api_tasks)."""
        with self.lock:
            self.c.execute("BEGIN")
            self.c.execute("DELETE FROM task_runs WHERE task_id = ?", (tid,))
            self.c.execute("DELETE FROM task_notes WHERE task_id = ?", (tid,))
            n = self.c.execute("DELETE FROM tasks WHERE id = ?", (tid,)).rowcount
            self.c.execute("COMMIT")
        return bool(n)

    def release_chats(self, tid: str) -> int:
        """The task's run chats become ordinary chats."""
        with self.lock:
            return self.c.execute("UPDATE threads SET settings = json_remove(settings, '$.task', '$.task_run', '$.unattended') "
                                  "WHERE json_extract(settings, '$.task') = ?", (tid,)).rowcount

    def detach_project(self, pid: str) -> list[str]:
        """A deleted project's tasks stand alone, turned off until someone looks at them."""
        ids = [r["id"] for r in self._rows("SELECT id FROM tasks WHERE project_id = ?", (pid,))]
        for tid in ids:
            self.update(tid, enabled=False)
            with self.lock:
                self.c.execute("UPDATE tasks SET project_id = NULL, only_own = 0 WHERE id = ?", (tid,))
        return ids

    def due(self, now: float) -> list[dict[str, Any]]:
        rows = self._rows("SELECT id FROM tasks WHERE enabled = 1 AND next_due IS NOT NULL AND next_due <= ? ORDER BY next_due", (now,))
        return [self.get(r["id"]) for r in rows]  # type: ignore[misc]

    # ---- runs -------------------------------------------------------------------------------------

    def runs(self, tid: str, limit: int = 50, before: float | None = None) -> list[dict[str, Any]]:
        sql, args = "SELECT * FROM task_runs WHERE task_id = ?", [tid]
        if before is not None:
            sql += " AND due < ?"
            args.append(before)
        return [_run(r) for r in self._rows(sql + " ORDER BY due DESC, rowid DESC LIMIT ?", [*args, limit])]

    def run(self, rid: str) -> dict[str, Any] | None:
        rows = self._rows("SELECT * FROM task_runs WHERE id = ?", (rid,))
        return _run(rows[0]) if rows else None

    def run_of_thread(self, thread_id: str) -> dict[str, Any] | None:
        rows = self._rows("SELECT * FROM task_runs WHERE thread_id = ?", (thread_id,))
        return _run(rows[0]) if rows else None

    def add_run(self, tid: str, due: float, state: str = "queued", **fields: Any) -> dict[str, Any]:
        rid = new_id("r_")
        cols = {"id": rid, "task_id": tid, "due": due, "state": state, **_run_cols(fields)}
        with self.lock:
            self.c.execute(f"INSERT INTO task_runs ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", list(cols.values()))
        return self.run(rid)  # type: ignore[return-value]

    def update_run(self, rid: str, **fields: Any) -> dict[str, Any] | None:
        cols = _run_cols(fields)
        if "state" in fields:
            if fields["state"] not in STATES:
                raise TaskError("bad_state", f"a run's state is one of {', '.join(STATES)}")
            cols["state"] = fields["state"]
        if cols:
            with self.lock:
                self.c.execute(f"UPDATE task_runs SET {', '.join(f'{k} = ?' for k in cols)} WHERE id = ?", [*cols.values(), rid])
        return self.run(rid)

    def active(self, tid: str | None = None) -> list[dict[str, Any]]:
        """Runs queued or running (of one task, or all), oldest first."""
        sql, args = "SELECT * FROM task_runs WHERE state IN ('queued', 'running')", []
        if tid:
            sql += " AND task_id = ?"
            args.append(tid)
        return [_run(r) for r in self._rows(sql + " ORDER BY due, rowid", args)]

    def unread(self) -> dict[str, Any]:
        rows = self._rows("SELECT task_id, COUNT(*) AS n FROM task_runs WHERE seen = 0 GROUP BY task_id")
        return {"count": sum(r["n"] for r in rows), "tasks": {r["task_id"]: r["n"] for r in rows}}

    def old_run_chats(self, now: float) -> list[str]:
        """Live run chats older than their task's `keep_days`: they get archived."""
        rows = self._rows("SELECT r.thread_id FROM task_runs r JOIN tasks k ON k.id = r.task_id JOIN threads t ON t.id = r.thread_id "
                          "WHERE t.archived = 0 AND r.ended IS NOT NULL AND r.ended < ? - k.keep_days * 86400 "
                          "AND t.state NOT IN ('running', 'waiting')", (now,))
        return [r["thread_id"] for r in rows]

    # ---- notes ------------------------------------------------------------------------------------

    def notes(self, tid: str) -> list[dict[str, Any]]:
        return self._rows("SELECT * FROM task_notes WHERE task_id = ? ORDER BY added, rowid", (tid,))

    def note(self, nid: str) -> dict[str, Any] | None:
        rows = self._rows("SELECT * FROM task_notes WHERE id = ?", (nid,))
        return rows[0] if rows else None

    def add_note(self, tid: str, text: str, thread_id: str | None = None) -> dict[str, Any]:
        text = _note_text(text)
        nid, now = new_id("n_"), self.clock()
        with self.lock:
            self.c.execute("BEGIN IMMEDIATE")
            try:
                if self.c.execute("SELECT COUNT(*) FROM task_notes WHERE task_id = ?", (tid,)).fetchone()[0] >= NOTES_MAX:
                    raise TaskError("too_many_notes", f"a task keeps at most {NOTES_MAX} notes; replace or remove one", 409)
                self.c.execute("INSERT INTO task_notes (id, task_id, text, thread_id, added, updated) VALUES (?, ?, ?, ?, ?, ?)",
                               (nid, tid, text, thread_id, now, now))
                self.c.execute("COMMIT")
            except BaseException:
                self.c.execute("ROLLBACK")
                raise
        return self.note(nid)  # type: ignore[return-value]

    def update_note(self, nid: str, text: str, thread_id: str | None = None) -> dict[str, Any] | None:
        with self.lock:
            self.c.execute("UPDATE task_notes SET text = ?, updated = ?, thread_id = COALESCE(?, thread_id) WHERE id = ?",
                           (_note_text(text), self.clock(), thread_id, nid))
        return self.note(nid)

    def remove_note(self, nid: str) -> bool:
        with self.lock:
            return bool(self.c.execute("DELETE FROM task_notes WHERE id = ?", (nid,)).rowcount)


_LAST = "(SELECT r.id FROM task_runs r WHERE r.task_id = k.id AND r.state != 'queued' ORDER BY r.due DESC, r.rowid DESC LIMIT 1)"
_UNREAD = "(SELECT COUNT(*) FROM task_runs r WHERE r.task_id = k.id AND r.seen = 0)"
RUN_COLS = {"thread_id", "started", "ended", "why", "late", "test", "refused", "judge", "seen"}


def _run_cols(fields: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for k, v in fields.items():
        if k in RUN_COLS:
            out[k] = int(bool(v)) if k in ("test", "seen") else v
    return out


def _run(r: dict[str, Any]) -> dict[str, Any]:
    r = dict(r)
    r["test"], r["seen"] = bool(r["test"]), bool(r["seen"])
    return r


def _note_text(text: Any) -> str:
    text = " ".join(str(text or "").split())
    if not text:
        raise TaskError("empty_note", "a note needs some text")
    if len(text) > NOTE_CHARS:
        raise TaskError("too_long", f"a note is at most {NOTE_CHARS} characters")
    return text
