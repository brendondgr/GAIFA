"""`hub.db`: SQLite in WAL mode, migrations by `PRAGMA user_version`.

One writer thread owns the only write connection; every write is queued to
it. Reads use one connection per thread, each with a lock held for the query, so
`close()` waits for a query still running in a worker thread instead of closing
the connection under it (which crashes SQLite). The async helpers run on
`asyncio.to_thread` (reads) or the writer thread (writes), so the event loop
never blocks on SQLite.
"""

from __future__ import annotations

import asyncio
import queue
import sqlite3
import threading
from collections.abc import Callable, Iterable
from concurrent.futures import Future
from pathlib import Path
from typing import Any, TypeVar

T = TypeVar("T")

# Each entry is one migration; its index + 1 is the user_version it sets.
MIGRATIONS: list[str] = [
    # 001
    """
    CREATE TABLE activity (
        id      INTEGER PRIMARY KEY AUTOINCREMENT,
        ts      REAL NOT NULL,
        service TEXT,
        level   TEXT NOT NULL CHECK (level IN ('info', 'warn', 'error')),
        text    TEXT NOT NULL,
        route   TEXT
    );
    CREATE INDEX activity_ts ON activity (ts);
    CREATE TABLE service_peaks (
        service    TEXT PRIMARY KEY,
        peak_bytes INTEGER NOT NULL,
        updated_ts REAL NOT NULL
    );
    CREATE TABLE kv (
        key   TEXT PRIMARY KEY,
        value TEXT
    );
    """,
    # 002: the outputs index (plan 4.1). `path` is relative to the outputs dir; `files` and
    # `meta` are JSON; `sig` (sizes + mtimes) tells a rescan whether an entry changed.
    """
    CREATE TABLE outputs (
        id         TEXT PRIMARY KEY,
        service    TEXT NOT NULL,
        kind       TEXT NOT NULL,
        title      TEXT NOT NULL,
        path       TEXT NOT NULL UNIQUE,
        is_dir     INTEGER NOT NULL DEFAULT 0,
        main       TEXT,
        preview    TEXT,
        size_bytes INTEGER NOT NULL DEFAULT 0,
        created_ts REAL NOT NULL,
        duration_s REAL,
        width      INTEGER,
        height     INTEGER,
        meta       TEXT NOT NULL DEFAULT '{}',
        files      TEXT NOT NULL DEFAULT '[]',
        search     TEXT NOT NULL DEFAULT '',
        sig        TEXT NOT NULL DEFAULT ''
    );
    CREATE INDEX outputs_created ON outputs (created_ts DESC, id);
    CREATE INDEX outputs_service ON outputs (service, created_ts DESC);
    """,
    # 003: metrics (plan 6.1, architecture §13). `series` names each time series once; samples
    # sit on a 10 s grid (`ts` in unix seconds). Rollups keep avg/min/max and the sample count
    # `n`, so coarser rollups average by weight. The event tables feed timelines and job stats.
    """
    CREATE TABLE series (
        id      INTEGER PRIMARY KEY,
        name    TEXT NOT NULL UNIQUE,
        label   TEXT NOT NULL,
        unit    TEXT NOT NULL,
        service TEXT,
        reset   TEXT,
        last_ts INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE metrics_raw (
        sid   INTEGER NOT NULL,
        ts    INTEGER NOT NULL,
        value REAL,
        PRIMARY KEY (sid, ts)
    ) WITHOUT ROWID;
    CREATE INDEX metrics_raw_ts ON metrics_raw (ts);
    CREATE TABLE metrics_1m (
        sid INTEGER NOT NULL, ts INTEGER NOT NULL,
        avg REAL, min REAL, max REAL, n INTEGER NOT NULL,
        PRIMARY KEY (sid, ts)
    ) WITHOUT ROWID;
    CREATE INDEX metrics_1m_ts ON metrics_1m (ts);
    CREATE TABLE metrics_1h (
        sid INTEGER NOT NULL, ts INTEGER NOT NULL,
        avg REAL, min REAL, max REAL, n INTEGER NOT NULL,
        PRIMARY KEY (sid, ts)
    ) WITHOUT ROWID;
    CREATE INDEX metrics_1h_ts ON metrics_1h (ts);
    CREATE TABLE service_states (
        id      INTEGER PRIMARY KEY AUTOINCREMENT,
        service TEXT NOT NULL,
        state   TEXT NOT NULL,
        from_ts REAL NOT NULL,
        to_ts   REAL
    );
    CREATE INDEX service_states_span ON service_states (service, from_ts);
    CREATE TABLE load_intervals (
        id      INTEGER PRIMARY KEY AUTOINCREMENT,
        service TEXT NOT NULL,
        from_ts REAL NOT NULL,
        to_ts   REAL
    );
    CREATE INDEX load_intervals_span ON load_intervals (service, from_ts);
    CREATE TABLE job_history (
        id       INTEGER PRIMARY KEY AUTOINCREMENT,
        service  TEXT NOT NULL,
        job_id   TEXT NOT NULL,
        label    TEXT NOT NULL,
        state    TEXT NOT NULL,
        start_ts REAL NOT NULL,
        end_ts   REAL,
        route    TEXT
    );
    CREATE INDEX job_history_start ON job_history (start_ts);
    CREATE INDEX job_history_open ON job_history (service, job_id, end_ts);
    CREATE INDEX activity_service ON activity (service, ts);
    """,
    # 004: agent tools (plan 13.2). A call that needs approval waits in `approvals` (the
    # arguments as the model sent them, and as finally run); `tool_calls` keeps each call's
    # state and full result (results shown to the model are capped; `full` reads them back).
    """
    CREATE TABLE approvals (
        id         TEXT PRIMARY KEY,
        tool       TEXT NOT NULL,
        arguments  TEXT NOT NULL,
        final      TEXT,
        ask_fields TEXT NOT NULL DEFAULT '[]',
        risk       TEXT NOT NULL,
        origin     TEXT NOT NULL DEFAULT '{}',
        state      TEXT NOT NULL CHECK (state IN ('pending', 'approved', 'denied', 'expired')),
        reason     TEXT,
        call_id    TEXT,
        created_ts REAL NOT NULL,
        decided_ts REAL
    );
    CREATE INDEX approvals_state ON approvals (state, created_ts);
    CREATE TABLE tool_calls (
        id          TEXT PRIMARY KEY,
        tool        TEXT NOT NULL,
        arguments   TEXT NOT NULL,
        origin      TEXT NOT NULL DEFAULT '{}',
        state       TEXT NOT NULL CHECK (state IN ('running', 'done', 'error', 'cancelled')),
        approval_id TEXT,
        job         TEXT,
        result      TEXT,
        created_ts  REAL NOT NULL,
        finished_ts REAL
    );
    CREATE INDEX tool_calls_created ON tool_calls (created_ts);
    """,
    # 005: sessions (plan 15.1): named snapshots of what runs and what's loaded.
    """
    CREATE TABLE sessions (
        id         TEXT PRIMARY KEY,
        name       TEXT NOT NULL,
        auto       INTEGER NOT NULL DEFAULT 0,
        snapshot   TEXT NOT NULL,
        created_ts REAL NOT NULL,
        updated_ts REAL NOT NULL
    );
    CREATE UNIQUE INDEX sessions_name ON sessions (name);
    """,
    # 006: complete tool records (plan 21.1): how long a call took, which arguments the hub chose
    # (`filled`: field → "default" | "pref:<id>" | "carried"), which the user changed on the card
    # (`edited`), and the calls refused before they ran.
    """
    ALTER TABLE tool_calls ADD COLUMN duration_ms INTEGER;
    ALTER TABLE tool_calls ADD COLUMN filled TEXT;
    ALTER TABLE approvals ADD COLUMN filled TEXT;
    ALTER TABLE approvals ADD COLUMN edited TEXT;
    CREATE TABLE tool_refusals (
        id         TEXT PRIMARY KEY,
        tool       TEXT NOT NULL,
        arguments  TEXT NOT NULL DEFAULT '{}',
        origin     TEXT NOT NULL DEFAULT '{}',
        code       TEXT NOT NULL,
        detail     TEXT NOT NULL,
        created_ts REAL NOT NULL
    );
    CREATE INDEX tool_refusals_created ON tool_refusals (created_ts);
    """,
    # 007: preferences (plan 21.2): utils/prefs.py.
    """
    CREATE TABLE prefs (
        id           TEXT PRIMARY KEY,
        scope        TEXT NOT NULL CHECK (scope IN ('tool', 'agent', 'thread')),
        tool         TEXT,
        field        TEXT,
        thread       TEXT,
        value        TEXT NOT NULL,
        "when"       TEXT NOT NULL DEFAULT '{}',
        cue          TEXT NOT NULL DEFAULT '',
        source       TEXT NOT NULL CHECK (source IN ('stated', 'inferred', 'carried')),
        state        TEXT NOT NULL CHECK (state IN ('proposed', 'active', 'retired', 'rejected')),
        confidence   REAL NOT NULL DEFAULT 1,
        evidence     TEXT NOT NULL DEFAULT '[]',
        seen         INTEGER NOT NULL DEFAULT 1,
        contradicted INTEGER NOT NULL DEFAULT 0,
        note         TEXT NOT NULL DEFAULT '',
        created_ts   REAL NOT NULL,
        updated_ts   REAL NOT NULL,
        last_used_ts REAL
    );
    CREATE INDEX prefs_tool ON prefs (tool, state);
    CREATE INDEX prefs_state ON prefs (state, updated_ts);
    """,
    # 008: thumbs on outputs (plan 21.4): the newest rating per output counts.
    """
    CREATE TABLE output_feedback (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        output_id  TEXT NOT NULL,
        value      TEXT NOT NULL CHECK (value IN ('up', 'down')),
        note       TEXT NOT NULL DEFAULT '',
        origin     TEXT NOT NULL DEFAULT '{}',
        ts         REAL NOT NULL
    );
    CREATE INDEX output_feedback_output ON output_feedback (output_id, ts);
    """,
    # 009: grants (plan 25.2): utils/tools/grants.py. `tool` is a name glob; `key` null covers every
    # call of it; `kind` is the tool's grant_key ("url:host", "arg:folder"); `thread` for scope thread.
    """
    CREATE TABLE grants (
        id           TEXT PRIMARY KEY,
        tool         TEXT NOT NULL,
        key          TEXT,
        kind         TEXT,
        risk         TEXT,
        scope        TEXT NOT NULL CHECK (scope IN ('thread', 'always')),
        thread       TEXT,
        created_ts   REAL NOT NULL,
        expires_ts   REAL,
        note         TEXT NOT NULL DEFAULT '',
        used         INTEGER NOT NULL DEFAULT 0,
        last_used_ts REAL,
        CHECK (scope = 'always' OR thread IS NOT NULL)
    );
    CREATE INDEX grants_thread ON grants (thread);
    """,
    # 010: the grant GAIFA ships (plan 26.2; the user's decision, 2026-10-20): web searches run without
    # asking. It is an ordinary `always` grant, so Settings → Permissions lists it and revoking it deletes
    # it; the migration runs once per database, so a revoked grant stays revoked.
    """
    INSERT OR IGNORE INTO grants (id, tool, key, kind, risk, scope, thread, created_ts, note)
    VALUES ('gr_default_web_search', 'web_search', 'search', 'const:search', 'network', 'always', NULL,
            CAST(strftime('%s', 'now') AS REAL),
            'Shipped with GAIFA: web searches run without asking. Revoke it to be asked each time.');
    """,
    # 011: the Auto mode's judged calls (plan 30.3, 30.5): utils/tools/judge.py. Settings → Permissions lists them.
    """
    CREATE TABLE judged (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        ts          REAL NOT NULL,
        tool        TEXT NOT NULL,
        verdict     TEXT NOT NULL CHECK (verdict IN ('allow', 'ask')),
        reason      TEXT NOT NULL DEFAULT '',
        source      TEXT NOT NULL DEFAULT '',
        rule        TEXT NOT NULL DEFAULT '',
        ms          REAL,
        model       TEXT NOT NULL DEFAULT '',
        summary     TEXT NOT NULL DEFAULT '',
        thread      TEXT,
        call_id     TEXT,
        approval_id TEXT
    );
    CREATE INDEX judged_ts ON judged (ts);
    """,
    # 012: hidden outputs (plan 30.9): the sidecar's `"hidden": true` (the web mod's saved pages) keeps an output
    # out of the lists people see. A row indexed before this with `hidden` in its meta is marked and re-described.
    """
    ALTER TABLE outputs ADD COLUMN hidden INTEGER NOT NULL DEFAULT 0;
    UPDATE outputs SET hidden = 1, sig = '' WHERE json_valid(meta) AND json_extract(meta, '$.hidden') = 1;
    """,
    # 013: a judged call the judge asked about in an unattended run (scheduled-tasks 2.1) was refused, not carded:
    # its verdict stays `ask` and `refused` says so (GET /api/judge/recent shows it as `refused`).
    """
    ALTER TABLE judged ADD COLUMN refused INTEGER NOT NULL DEFAULT 0;
    """,
]

_STOP = object()


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=10, check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 10000")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def migrate(conn: sqlite3.Connection, migrations: list[str] = MIGRATIONS) -> int:
    """Apply the migrations past the current user_version. Returns the new version."""
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    for n, sql in enumerate(migrations[version:], start=version + 1):
        try:
            conn.executescript(f"BEGIN;\n{sql}\nPRAGMA user_version = {n};\nCOMMIT;")
        except sqlite3.Error:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
    return conn.execute("PRAGMA user_version").fetchone()[0]


class Database:
    def __init__(self, path: Path, migrations: list[str] = MIGRATIONS) -> None:
        self.path = path
        self._migrations = migrations
        self._writer: sqlite3.Connection | None = None
        self._queue: queue.SimpleQueue[Any] = queue.SimpleQueue()
        self._thread: threading.Thread | None = None
        self._local = threading.local()
        self._readers: list[tuple[sqlite3.Connection, threading.Lock]] = []
        self._readers_lock = threading.Lock()
        self._closed = False

    # lifecycle ------------------------------------------------------------

    def open(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._writer = _connect(self.path)
        self._closed = False
        self._writer.execute("PRAGMA journal_mode = WAL")
        self._writer.execute("PRAGMA synchronous = NORMAL")
        migrate(self._writer, self._migrations)
        self._thread = threading.Thread(target=self._write_loop, name="gaifa-db-writer", daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._closed = True
        if self._thread:
            self._queue.put(_STOP)
            self._thread.join()
            self._thread = None
        if self._writer:
            self._writer.close()
            self._writer = None
        with self._readers_lock:
            for c, lock in self._readers:
                with lock:  # a query in flight in another thread finishes first
                    c.close()
            self._readers.clear()
        self._local = threading.local()

    @property
    def version(self) -> int:
        return self._read(lambda c: c.execute("PRAGMA user_version").fetchone()[0])

    # writes ---------------------------------------------------------------

    def _write_loop(self) -> None:
        while (item := self._queue.get()) is not _STOP:
            fn, fut = item
            if not fut.set_running_or_notify_cancel():
                continue
            try:
                self._writer.execute("BEGIN IMMEDIATE")
                try:
                    result = fn(self._writer)
                except BaseException:
                    self._writer.execute("ROLLBACK")
                    raise
                self._writer.execute("COMMIT")
                fut.set_result(result)
            except BaseException as e:  # noqa: BLE001 - handed to the caller
                fut.set_exception(e)

    def submit(self, fn: Callable[[sqlite3.Connection], T]) -> Future[T]:
        """Queue `fn(conn)` on the writer thread, in its own transaction."""
        if self._thread is None:
            raise RuntimeError("database is not open")
        fut: Future[T] = Future()
        self._queue.put((fn, fut))
        return fut

    async def write(self, fn: Callable[[sqlite3.Connection], T]) -> T:
        return await asyncio.wrap_future(self.submit(fn))

    async def execute(self, sql: str, params: Iterable[Any] = ()) -> int:
        """Run one write statement. Returns lastrowid (inserts) or rowcount."""

        def run(c: sqlite3.Connection) -> int:
            cur = c.execute(sql, tuple(params))
            return cur.lastrowid if sql.lstrip().upper().startswith("INSERT") else cur.rowcount

        return await self.write(run)

    async def executemany(self, sql: str, rows: Iterable[Iterable[Any]]) -> int:
        rows = [tuple(r) for r in rows]
        return await self.write(lambda c: c.executemany(sql, rows).rowcount)

    # reads ----------------------------------------------------------------

    def _read(self, fn: Callable[[sqlite3.Connection], T]) -> T:
        """`fn(conn)` on this thread's reader connection, holding its lock."""
        reader = getattr(self._local, "reader", None)
        if reader is None:
            if self._closed:
                raise RuntimeError("database is closed")
            conn = _connect(self.path)
            conn.execute("PRAGMA query_only = ON")
            reader = self._local.reader = (conn, threading.Lock())
            with self._readers_lock:
                self._readers.append(reader)
        conn, lock = reader
        with lock:
            if self._closed:
                raise RuntimeError("database is closed")
            return fn(conn)

    def fetchall_sync(self, sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
        return self._read(lambda c: [dict(r) for r in c.execute(sql, tuple(params)).fetchall()])

    def fetchone_sync(self, sql: str, params: Iterable[Any] = ()) -> dict[str, Any] | None:
        row = self._read(lambda c: c.execute(sql, tuple(params)).fetchone())
        return dict(row) if row else None

    async def fetchall(self, sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self.fetchall_sync, sql, tuple(params))

    async def fetchone(self, sql: str, params: Iterable[Any] = ()) -> dict[str, Any] | None:
        return await asyncio.to_thread(self.fetchone_sync, sql, tuple(params))
