"""The library's database, `data/databases/embed.db` (plan 28.2): which outputs are indexed, their chunks with
float16 vectors at 768-d, and the named collections. Search is brute-force cosine over a cached matrix."""

from __future__ import annotations

import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

DIM = 768
SCHEMA = """
CREATE TABLE IF NOT EXISTS outputs (
    id TEXT PRIMARY KEY, kind TEXT, title TEXT, sig TEXT, state TEXT NOT NULL,   -- pending | done | skipped | failed
    error TEXT, chunks INTEGER NOT NULL DEFAULT 0, attempts INTEGER NOT NULL DEFAULT 0,
    created_ts REAL, indexed_ts REAL);
CREATE INDEX IF NOT EXISTS outputs_state ON outputs(state, created_ts);
CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY, output_id TEXT NOT NULL, kind TEXT NOT NULL,        -- text | meta | image | audio | video
    page INTEGER, line INTEGER, "offset" INTEGER, start_s REAL, end_s REAL, snippet TEXT, vector BLOB NOT NULL,
    text TEXT);                                                              -- a text chunk's words, for the best line
CREATE INDEX IF NOT EXISTS chunks_output ON chunks(output_id);
CREATE TABLE IF NOT EXISTS collections (id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, created_ts REAL);
CREATE TABLE IF NOT EXISTS chats (                                           -- plan 28.5: the `chats` collection
    thread_id TEXT PRIMARY KEY, title TEXT, summary TEXT NOT NULL, created_ts REAL, updated_ts REAL,
    state TEXT NOT NULL, vector BLOB);                                       -- pending | done
CREATE TABLE IF NOT EXISTS texts (                                           -- structured-memory 2.1: named text collections
    ns TEXT NOT NULL, id TEXT NOT NULL, title TEXT NOT NULL DEFAULT '', text TEXT NOT NULL, meta TEXT NOT NULL DEFAULT '{}',
    state TEXT NOT NULL, vector BLOB, updated_ts REAL, PRIMARY KEY (ns, id));
CREATE INDEX IF NOT EXISTS texts_state ON texts(state, updated_ts);
CREATE TABLE IF NOT EXISTS collection_outputs (
    collection_id TEXT NOT NULL REFERENCES collections(id) ON DELETE CASCADE, output_id TEXT NOT NULL,
    PRIMARY KEY (collection_id, output_id));
"""
MAX_ATTEMPTS = 3


@dataclass
class Chunk:
    kind: str
    vector: np.ndarray
    snippet: str = ""
    text: str | None = None
    page: int | None = None
    line: int | None = None
    offset: int | None = None
    start_s: float | None = None
    end_s: float | None = None


@dataclass
class Matrix:
    """Every chunk's vector as one float32 array, with what each row is."""
    ids: np.ndarray                                     # chunk ids
    outputs: list[str]
    kinds: list[str]
    vectors: np.ndarray = field(repr=False)


class Store:
    def __init__(self, path: Path, dim: int = DIM):
        self.dim = dim                                  # the model's vector size (capability-enablement 7.3)
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript(SCHEMA)
        if "text" not in {r[1] for r in self.db.execute("PRAGMA table_info(chunks)")}:     # a database from before
            self.db.execute("ALTER TABLE chunks ADD COLUMN text TEXT")
        self.lock = threading.RLock()
        self.version = 0                                # bumped on every chunk change; the matrix cache follows it
        self._matrix: tuple[int, Matrix] | None = None

    def close(self) -> None:
        self.db.close()

    def _rows(self, sql: str, args: tuple | list = ()) -> list[dict[str, Any]]:
        with self.lock:
            return [dict(r) for r in self.db.execute(sql, args)]

    # outputs -------------------------------------------------------------------------------

    def sigs(self) -> dict[str, str]:
        return {r["id"]: r["sig"] for r in self._rows("SELECT id, sig FROM outputs")}

    def all(self) -> list[dict[str, Any]]:
        return self._rows("SELECT * FROM outputs")

    def get(self, oid: str) -> dict[str, Any] | None:
        rows = self._rows("SELECT * FROM outputs WHERE id = ?", (oid,))
        return rows[0] if rows else None

    def queue(self, rec: dict[str, Any], sig: str) -> None:
        """Mark an output to be indexed (new or changed). Its old chunks stay searchable until it's done."""
        with self.lock:
            self.db.execute(
                "INSERT INTO outputs (id, kind, title, sig, state, created_ts) VALUES (?, ?, ?, ?, 'pending', ?) "
                "ON CONFLICT(id) DO UPDATE SET kind = excluded.kind, title = excluded.title, sig = excluded.sig, "
                "state = 'pending', error = NULL, attempts = 0, created_ts = excluded.created_ts",
                (rec["id"], rec.get("kind"), rec.get("title"), sig, rec.get("created_ts")))

    def pending(self, limit: int = 1) -> list[dict[str, Any]]:
        """Newest first: what was just made is the likeliest thing to be searched for."""
        return self._rows("SELECT * FROM outputs WHERE state = 'pending' ORDER BY created_ts DESC LIMIT ?", (limit,))

    def finish(self, oid: str, chunks: list[Chunk], state: str = "done", sig: str | None = None) -> None:
        """Replace the output's chunks in one transaction (a restart never sees half an output). If its sig
        changed meanwhile (`sig` given and different), it stays pending for another pass; if it was deleted
        meanwhile (no row), no chunks are kept."""
        with self.lock:
            self.db.execute("BEGIN")
            try:
                self.db.execute("DELETE FROM chunks WHERE output_id = ?", (oid,))
                row = self.get(oid)
                if row is None:
                    self.db.execute("COMMIT")
                    self.version += 1
                    return
                self.db.executemany(
                    'INSERT INTO chunks (output_id, kind, page, line, "offset", start_s, end_s, snippet, vector, text) '
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [(oid, c.kind, c.page, c.line, c.offset, c.start_s, c.end_s, c.snippet[:400],
                      np.asarray(c.vector, dtype=np.float16)[:self.dim].tobytes(), c.text) for c in chunks])
                still = sig is None or row["sig"] == sig
                self.db.execute("UPDATE outputs SET state = ?, chunks = ?, error = NULL, indexed_ts = ? WHERE id = ?",
                                (state if still else "pending", len(chunks), time.time(), oid))
                self.db.execute("COMMIT")
            except BaseException:
                self.db.execute("ROLLBACK")
                raise
            self.version += 1

    def fail(self, oid: str, error: str) -> None:
        """Count a failed attempt; after MAX_ATTEMPTS it stays `failed` until the output changes."""
        with self.lock:
            self.db.execute("UPDATE outputs SET attempts = attempts + 1, error = ?, "
                            "state = CASE WHEN attempts + 1 >= ? THEN 'failed' ELSE 'pending' END WHERE id = ?",
                            (error[:500], MAX_ATTEMPTS, oid))

    def defer(self, oid: str) -> None:
        """Push an output to the back of the queue (it was picked but couldn't be done now)."""
        with self.lock:
            self.db.execute("UPDATE outputs SET created_ts = COALESCE(created_ts, 0) - 1e9 WHERE id = ?", (oid,))

    def delete(self, oid: str) -> bool:
        with self.lock:
            n = self.db.execute("DELETE FROM outputs WHERE id = ?", (oid,)).rowcount
            self.db.execute("DELETE FROM chunks WHERE output_id = ?", (oid,))
            self.db.execute("DELETE FROM collection_outputs WHERE output_id = ?", (oid,))
            self.version += 1
            return n > 0

    def drop_orphans(self) -> int:
        """Chunks whose output is gone (from before `finish` checked for the row). Returns how many."""
        with self.lock:
            n = self.db.execute("DELETE FROM chunks WHERE output_id NOT IN (SELECT id FROM outputs)").rowcount
            if n:
                self.version += 1
            return n

    def counts(self) -> dict[str, int]:
        out = {s: 0 for s in ("pending", "done", "skipped", "failed")}
        out.update({r["state"]: r["n"] for r in self._rows("SELECT state, COUNT(*) AS n FROM outputs GROUP BY state")})
        out["chunks"] = self._rows("SELECT COUNT(*) AS n FROM chunks")[0]["n"]
        return out

    # chunks and search ---------------------------------------------------------------------

    def chunks_of(self, oid: str) -> list[dict[str, Any]]:
        return self._rows('SELECT id, kind, page, line, "offset", start_s, end_s, snippet FROM chunks '
                          "WHERE output_id = ? ORDER BY id", (oid,))

    def chunk_rows(self, ids: list[int]) -> dict[int, dict[str, Any]]:
        if not ids:
            return {}
        marks = ",".join("?" * len(ids))
        rows = self._rows(f'SELECT c.id, c.output_id, c.kind, c.page, c.line, c."offset", c.start_s, c.end_s, c.snippet, '
                          f"c.text, o.kind AS output_kind, o.title FROM chunks c JOIN outputs o ON o.id = c.output_id "
                          f"WHERE c.id IN ({marks})", ids)
        return {r["id"]: r for r in rows}

    def matrix(self) -> Matrix:
        """All vectors, cached until the next change. 768 float32 a chunk: 100k chunks are 300 MB, the point
        where `sqlite-vec` (or a float16 matrix) becomes the next step."""
        with self.lock:
            if self._matrix and self._matrix[0] == self.version:
                return self._matrix[1]
            rows = self.db.execute("SELECT id, output_id, kind, vector FROM chunks ORDER BY id").fetchall()
            version = self.version
        vecs = (np.frombuffer(b"".join(r["vector"] for r in rows), dtype=np.float16).reshape(len(rows), self.dim)
                .astype(np.float32) if rows else np.zeros((0, self.dim), np.float32))
        m = Matrix(np.array([r["id"] for r in rows], dtype=np.int64), [r["output_id"] for r in rows],
                   [r["kind"] for r in rows], vecs)
        with self.lock:
            self._matrix = (version, m)
        return m

    # chats (plan 28.5): a summary a chat, one vector each ---------------------------------------

    def put_chat(self, tid: str, title: str, summary: str, created_ts: float | None, updated_ts: float | None) -> None:
        with self.lock:
            self.db.execute("INSERT INTO chats (thread_id, title, summary, created_ts, updated_ts, state) "
                            "VALUES (?, ?, ?, ?, ?, 'pending') ON CONFLICT(thread_id) DO UPDATE SET title = excluded.title, "
                            "summary = excluded.summary, created_ts = excluded.created_ts, updated_ts = excluded.updated_ts, "
                            "state = 'pending'", (tid, title, summary, created_ts, updated_ts))

    def chats_pending(self, limit: int = 8) -> list[dict[str, Any]]:
        return self._rows("SELECT thread_id, title, summary FROM chats WHERE state = 'pending' "
                          "ORDER BY updated_ts DESC LIMIT ?", (limit,))

    def finish_chat(self, tid: str, summary: str, vector: np.ndarray) -> None:
        """Done only if the summary is still the one embedded (a newer one stays pending)."""
        with self.lock:
            self.db.execute("UPDATE chats SET state = 'done', vector = ? WHERE thread_id = ? AND summary = ?",
                            (np.asarray(vector, dtype=np.float16)[:self.dim].tobytes(), tid, summary))

    def delete_chat(self, tid: str) -> bool:
        with self.lock:
            return self.db.execute("DELETE FROM chats WHERE thread_id = ?", (tid,)).rowcount > 0

    def chats(self) -> list[dict[str, Any]]:
        return self._rows("SELECT thread_id, title, summary, created_ts, updated_ts, state, vector FROM chats")

    def chat_counts(self) -> dict[str, int]:
        out = {"pending": 0, "done": 0}
        out.update({r["state"]: r["n"] for r in self._rows("SELECT state, COUNT(*) AS n FROM chats GROUP BY state")})
        return out

    # texts (structured-memory 2.1): named collections of short texts, one vector each, like the chats ----------

    def put_text(self, ns: str, tid: str, title: str, text: str, meta: str) -> None:
        with self.lock:
            self.db.execute("INSERT INTO texts (ns, id, title, text, meta, state, updated_ts) VALUES (?, ?, ?, ?, ?, 'pending', ?) "
                            "ON CONFLICT(ns, id) DO UPDATE SET title = excluded.title, meta = excluded.meta, updated_ts = excluded.updated_ts, "
                            "state = CASE WHEN texts.text = excluded.text AND texts.title = excluded.title AND texts.vector IS NOT NULL "
                            "THEN texts.state ELSE 'pending' END, text = excluded.text", (ns, tid, title, text, meta, time.time()))

    def texts_pending(self, limit: int = 8) -> list[dict[str, Any]]:
        return self._rows("SELECT ns, id, title, text FROM texts WHERE state = 'pending' ORDER BY updated_ts DESC LIMIT ?", (limit,))

    def finish_text(self, ns: str, tid: str, text: str, vector: np.ndarray) -> None:
        with self.lock:
            self.db.execute("UPDATE texts SET state = 'done', vector = ? WHERE ns = ? AND id = ? AND text = ?",
                            (np.asarray(vector, dtype=np.float16)[:self.dim].tobytes(), ns, tid, text))

    def delete_texts(self, ns: str, ids: list[str] | None = None) -> int:
        with self.lock:
            if ids is None:
                return self.db.execute("DELETE FROM texts WHERE ns = ?", (ns,)).rowcount
            return sum(self.db.execute("DELETE FROM texts WHERE ns = ? AND id = ?", (ns, i)).rowcount for i in ids)

    def texts(self, ns: str, ids: list[str] | None = None) -> list[dict[str, Any]]:
        rows = self._rows("SELECT id, title, meta, state, vector FROM texts WHERE ns = ?", (ns,))
        return [r for r in rows if ids is None or r["id"] in set(ids)]

    def text_counts(self, ns: str) -> dict[str, int]:
        out = {"pending": 0, "done": 0}
        out.update({r["state"]: r["n"] for r in self._rows("SELECT state, COUNT(*) AS n FROM texts WHERE ns = ? GROUP BY state", (ns,))})
        return out

    def copy_from(self, other: "Store") -> dict[str, int]:
        """What another model's index holds that isn't an output (capability-enablement 7.3): chat summaries and
        texts (to be embedded here, unless this index already has the same words embedded) and collections."""
        n = {"chats": 0, "texts": 0, "collections": 0}
        have = {r["thread_id"]: r for r in self.chats()}
        for r in other.chats():
            h = have.get(r["thread_id"])
            if h is None or h["summary"] != r["summary"] or not h["vector"]:
                self.put_chat(r["thread_id"], r["title"], r["summary"], r["created_ts"], r["updated_ts"])
                n["chats"] += 1
        for r in other._rows("SELECT ns, id, title, text, meta FROM texts"):
            self.put_text(r["ns"], r["id"], r["title"], r["text"], r["meta"])      # same words and a vector: kept
            n["texts"] += 1
        mine = {c["name"] for c in self.collections()}
        for c in other.collections():
            if c["name"] not in mine:
                self.save_collection(c["name"], c["outputs"])
                n["collections"] += 1
        return n

    def queued(self) -> bool:
        """Chat summaries or texts waiting to be embedded (they go between outputs)."""
        return bool(self.chats_pending(1) or self.texts_pending(1))

    # collections ---------------------------------------------------------------------------

    def collections(self) -> list[dict[str, Any]]:
        cols = self._rows("SELECT * FROM collections ORDER BY created_ts")
        members = self._rows("SELECT collection_id, output_id FROM collection_outputs ORDER BY rowid")
        for c in cols:
            c["outputs"] = [m["output_id"] for m in members if m["collection_id"] == c["id"]]
        return cols

    def collection(self, cid: str) -> dict[str, Any] | None:
        return next((c for c in self.collections() if c["id"] == cid or c["name"] == cid), None)

    def save_collection(self, name: str, outputs: list[str], cid: str | None = None) -> dict[str, Any]:
        with self.lock:
            self.db.execute("BEGIN")
            try:
                if cid is None:
                    cid = "c_" + uuid.uuid4().hex[:10]
                    self.db.execute("INSERT INTO collections (id, name, created_ts) VALUES (?, ?, ?)", (cid, name, time.time()))
                else:
                    self.db.execute("UPDATE collections SET name = ? WHERE id = ?", (name, cid))
                    self.db.execute("DELETE FROM collection_outputs WHERE collection_id = ?", (cid,))
                self.db.executemany("INSERT OR IGNORE INTO collection_outputs (collection_id, output_id) VALUES (?, ?)",
                                    [(cid, o) for o in outputs])
                self.db.execute("COMMIT")
            except BaseException:
                self.db.execute("ROLLBACK")
                raise
        return self.collection(cid) or {}

    def delete_collection(self, cid: str) -> bool:
        with self.lock:
            return self.db.execute("DELETE FROM collections WHERE id = ?", (cid,)).rowcount > 0
