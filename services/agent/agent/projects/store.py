"""ProjectStore (plan projects 1.1): projects and their sources, in `agent.db`.

A project is `{id, name, description, instructions, environments, own_env, defaults, memory_entity, pinned, created,
updated}`; `environments` lists workspace environment ids (the first is its primary one), `own_env` is the hidden
environment that holds its own folders (Phase 2), `defaults` is `{model, mode, disabled, pinned, mcp_on, skills}` for
its new chats. A source is a file (an output id) or a web page (a URL and the newest output that holds its text).
A chat belongs to a project through `threads.settings.project` (store.PROJ_OF).
"""

from __future__ import annotations

import json
import secrets
import time
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    description   TEXT NOT NULL DEFAULT '',
    instructions  TEXT NOT NULL DEFAULT '',
    environments  TEXT NOT NULL DEFAULT '[]',
    own_env       TEXT,
    defaults      TEXT NOT NULL DEFAULT '{}',
    memory_entity TEXT,
    pinned        INTEGER NOT NULL DEFAULT 0,
    created       REAL NOT NULL,
    updated       REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS project_sources (
    id         TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    kind       TEXT NOT NULL,
    output_id  TEXT,
    url        TEXT,
    title      TEXT NOT NULL DEFAULT '',
    max_age_s  INTEGER,
    fetched    REAL,
    chars      INTEGER NOT NULL DEFAULT 0,
    status     TEXT NOT NULL DEFAULT 'ok',
    error      TEXT,
    added      REAL NOT NULL,
    position   INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS project_sources_project ON project_sources (project_id, position);
"""
MAX_SOURCES = 200
NAME_MAX = 120
DESCRIPTION_MAX = 2000
INSTRUCTIONS_MAX = 16_000
DEFAULT_MAX_AGE = 3600          # a page is fetched again when a question needs it and it's older than this
DEFAULT_KEYS = ("model", "mode", "disabled", "pinned", "mcp_on", "skills")
SORTS = {"activity": "activity DESC", "name": "lower(p.name) ASC, activity DESC", "created": "p.created DESC"}
KINDS = ("file", "page")
STATES = ("ok", "fetching", "error")


class ProjectError(Exception):
    def __init__(self, code: str, detail: str, status: int = 422) -> None:
        super().__init__(detail)
        self.code, self.detail, self.status = code, detail, status


def new_id(prefix: str) -> str:
    return prefix + secrets.token_hex(5)


def clean_defaults(d: dict[str, Any] | None) -> dict[str, Any]:
    """Only the keys a project sets for its chats; lists stay lists of strings."""
    out: dict[str, Any] = {}
    for k, v in (d or {}).items():
        if k not in DEFAULT_KEYS or v is None:
            continue
        if k in ("disabled", "pinned", "mcp_on", "skills"):
            v = [str(x) for x in v][:64] if isinstance(v, list) else []
        else:
            v = str(v)[:200]
        out[k] = v
    return out


class ProjectStore:
    def __init__(self, store: Any, clock: Any = time.time) -> None:
        self.c, self.lock, self.clock = store._c, store._lock, clock
        with self.lock:
            self.c.executescript(SCHEMA)

    def _rows(self, sql: str, args: Any = ()) -> list[dict[str, Any]]:
        with self.lock:
            return [dict(r) for r in self.c.execute(sql, args).fetchall()]

    @staticmethod
    def _project(r: dict[str, Any] | None) -> dict[str, Any] | None:
        if r is None:
            return None
        p = dict(r)
        p["environments"] = json.loads(p.get("environments") or "[]")
        p["defaults"] = json.loads(p.get("defaults") or "{}")
        p["pinned"] = bool(p.get("pinned"))
        return p

    # ---- projects ---------------------------------------------------------------------------------

    def create(self, name: str, description: str = "", instructions: str = "", environments: list[str] | None = None,
               defaults: dict[str, Any] | None = None) -> dict[str, Any]:
        name = _name(name)
        _check_len("description", description, DESCRIPTION_MAX)
        _check_len("instructions", instructions, INSTRUCTIONS_MAX)
        pid, now = new_id("p_"), self.clock()
        with self.lock:
            self.c.execute("INSERT INTO projects (id, name, description, instructions, environments, defaults, created, updated) "
                           "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                           (pid, name, description or "", instructions or "", json.dumps(_envs(environments)),
                            json.dumps(clean_defaults(defaults)), now, now))
        return self.get(pid)  # type: ignore[return-value]

    def get(self, pid: str) -> dict[str, Any] | None:
        rows = self._rows(f"SELECT p.*, {_ACTIVITY} AS activity, {_CHATS} AS chats, {_SOURCES} AS source_count "
                          "FROM projects p WHERE p.id = ?", (pid,))
        return self._project(rows[0] if rows else None)

    def list(self, q: str | None = None, sort: str = "activity") -> list[dict[str, Any]]:
        """Pinned first, then by `sort` (activity: the newest of the project's own change and its chats'; name A to Z;
        created, newest first); `q` searches names and descriptions."""
        sql, args = (f"SELECT p.*, {_ACTIVITY} AS activity, {_CHATS} AS chats, {_SOURCES} AS source_count FROM projects p", [])
        if q:
            sql += " WHERE (p.name LIKE ? OR p.description LIKE ?)"
            args += [f"%{q}%", f"%{q}%"]
        sql += " ORDER BY p.pinned DESC, " + SORTS.get(sort, SORTS["activity"])
        return [self._project(r) for r in self._rows(sql, args)]  # type: ignore[misc]

    def update(self, pid: str, **fields: Any) -> dict[str, Any] | None:
        allowed = {"name", "description", "instructions", "environments", "own_env", "defaults", "memory_entity", "pinned"}
        sets, args = [], []
        for k, v in fields.items():
            if k not in allowed or v is None and k not in ("own_env", "memory_entity"):
                continue
            if k == "name":
                v = _name(v)
            elif k == "description":
                _check_len(k, v, DESCRIPTION_MAX)
            elif k == "instructions":
                _check_len(k, v, INSTRUCTIONS_MAX)
            elif k == "environments":
                v = json.dumps(_envs(v))
            elif k == "defaults":
                v = json.dumps(clean_defaults(v))
            elif k == "pinned":
                v = int(bool(v))
            sets.append(f"{k} = ?")
            args.append(v)
        if sets:
            sets.append("updated = ?")
            args += [self.clock(), pid]
            with self.lock:
                self.c.execute(f"UPDATE projects SET {', '.join(sets)} WHERE id = ?", args)
        return self.get(pid)

    def delete(self, pid: str) -> bool:
        """The project and its sources (and their chunks, Phase 3); its chats are left to the caller (api_projects)."""
        with self.lock:
            self.c.execute("BEGIN")
            self.c.execute("DELETE FROM project_sources WHERE project_id = ?", (pid,))
            self._drop_chunks(pid)
            n = self.c.execute("DELETE FROM projects WHERE id = ?", (pid,)).rowcount
            self.c.execute("COMMIT")
        return bool(n)

    def _drop_chunks(self, pid: str) -> None:
        """Phase 3 keeps each source's chunks in `project_chunks`; nothing to drop before that table exists."""
        if self.c.execute("SELECT 1 FROM sqlite_master WHERE name = 'project_chunks'").fetchone():
            self.c.execute("DELETE FROM project_chunks WHERE sid IN (SELECT id FROM project_sources WHERE project_id = ?) "
                           "OR pid = ?", (pid, pid))

    def release_chats(self, pid: str) -> int:
        """The project's chats become ordinary chats (their environment kept); their `updated` stays, so the list
        doesn't reorder."""
        with self.lock:
            return self.c.execute("UPDATE threads SET settings = json_remove(settings, '$.project') "
                                  "WHERE json_extract(settings, '$.project') = ?", (pid,)).rowcount

    def set_chats_environment(self, pid: str, env: str) -> int:
        """Every chat of the project gets `env` (its primary environment) as `settings.environment`, in one UPDATE."""
        with self.lock:
            return self.c.execute("UPDATE threads SET settings = json_set(settings, '$.environment', ?) "
                                  "WHERE json_extract(settings, '$.project') = ?", (env, pid)).rowcount

    def by_name(self, name: str) -> dict[str, Any] | None:
        rows = self._rows("SELECT id FROM projects WHERE lower(name) = lower(?)", (name.strip(),))
        return self.get(rows[0]["id"]) if rows else None

    # ---- sources ----------------------------------------------------------------------------------

    def sources(self, pid: str) -> list[dict[str, Any]]:
        return self._rows("SELECT * FROM project_sources WHERE project_id = ? ORDER BY position, added", (pid,))

    def source(self, sid: str) -> dict[str, Any] | None:
        rows = self._rows("SELECT * FROM project_sources WHERE id = ?", (sid,))
        return rows[0] if rows else None

    def add_source(self, pid: str, kind: str, output_id: str | None = None, url: str | None = None, title: str = "",
                   max_age_s: int | None = DEFAULT_MAX_AGE, status: str = "ok", chars: int = 0,
                   fetched: float | None = None) -> dict[str, Any]:
        if kind not in KINDS:
            raise ProjectError("bad_kind", f"a source is a file or a page, not {kind!r}")
        if kind == "file" and not output_id:
            raise ProjectError("bad_source", "a file source needs output_id")
        if kind == "page" and not url:
            raise ProjectError("bad_source", "a page source needs url")
        sid, now = new_id("src_"), self.clock()
        with self.lock:
            self.c.execute("BEGIN IMMEDIATE")
            try:
                n, top = self.c.execute("SELECT COUNT(*), COALESCE(MAX(position), -1) FROM project_sources WHERE project_id = ?",
                                        (pid,)).fetchone()
                if n >= MAX_SOURCES:
                    raise ProjectError("too_many_sources", f"a project holds at most {MAX_SOURCES} files and pages", 409)
                if kind == "file" and self.c.execute("SELECT 1 FROM project_sources WHERE project_id = ? AND output_id = ? "
                                                     "AND kind = 'file'", (pid, output_id)).fetchone():
                    raise ProjectError("exists", "that file is in the project already", 409)
                if kind == "page" and self.c.execute("SELECT 1 FROM project_sources WHERE project_id = ? AND url = ?",
                                                     (pid, url)).fetchone():
                    raise ProjectError("exists", "that page is in the project already", 409)
                self.c.execute("INSERT INTO project_sources (id, project_id, kind, output_id, url, title, max_age_s, fetched, chars, "
                               "status, added, position) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                               (sid, pid, kind, output_id, url, title[:300], max_age_s if kind == "page" else None, fetched,
                                int(chars), status, now, top + 1))
                self.c.execute("UPDATE projects SET updated = ? WHERE id = ?", (now, pid))
                self.c.execute("COMMIT")
            except BaseException:
                self.c.execute("ROLLBACK")
                raise
        return self.source(sid)  # type: ignore[return-value]

    def update_source(self, sid: str, **fields: Any) -> dict[str, Any] | None:
        allowed = {"output_id", "title", "max_age_s", "fetched", "chars", "status", "error", "position"}
        sets, args = [], []
        for k, v in fields.items():
            if k not in allowed:
                continue
            if k == "status" and v not in STATES:
                raise ProjectError("bad_status", f"status is one of {', '.join(STATES)}")
            if k == "title":
                v = str(v or "")[:300]
            sets.append(f"{k} = ?")
            args.append(v)
        if sets:
            with self.lock:
                self.c.execute(f"UPDATE project_sources SET {', '.join(sets)} WHERE id = ?", [*args, sid])
        return self.source(sid)

    def remove_source(self, sid: str) -> bool:
        with self.lock:
            if self.c.execute("SELECT 1 FROM sqlite_master WHERE name = 'project_chunks'").fetchone():
                self.c.execute("DELETE FROM project_chunks WHERE sid = ?", (sid,))
            return bool(self.c.execute("DELETE FROM project_sources WHERE id = ?", (sid,)).rowcount)

    def reorder(self, pid: str, order: list[str]) -> list[dict[str, Any]]:
        """The sources in this order (ids not named keep their order after the named ones)."""
        have = [s["id"] for s in self.sources(pid)]
        named = [s for s in order if s in have]
        rest = [s for s in have if s not in named]
        with self.lock:
            self.c.execute("BEGIN")
            for i, sid in enumerate(named + rest):
                self.c.execute("UPDATE project_sources SET position = ? WHERE id = ?", (i, sid))
            self.c.execute("COMMIT")
        return self.sources(pid)


_ACTIVITY = ("MAX(p.updated, COALESCE((SELECT MAX(t.updated) FROM threads t "
             "WHERE json_extract(t.settings, '$.project') = p.id), 0))")
_CHATS = "(SELECT COUNT(*) FROM threads t WHERE json_extract(t.settings, '$.project') = p.id AND t.archived = 0)"
_SOURCES = "(SELECT COUNT(*) FROM project_sources s WHERE s.project_id = p.id)"


def _name(name: Any) -> str:
    name = " ".join(str(name or "").split())
    if not name:
        raise ProjectError("bad_name", "a project needs a name")
    if len(name) > NAME_MAX:
        raise ProjectError("bad_name", f"a project's name is at most {NAME_MAX} characters")
    return name


def _check_len(what: str, text: Any, most: int) -> None:
    if text is not None and len(str(text)) > most:
        raise ProjectError("too_long", f"the {what} are at most {most:,} characters" if what == "instructions"
                           else f"the {what} is at most {most:,} characters")


def _envs(envs: list[str] | None) -> list[str]:
    out: list[str] = []
    for e in envs or []:
        e = str(e).strip()
        if e and e not in out:
            out.append(e)
    return out[:16]
