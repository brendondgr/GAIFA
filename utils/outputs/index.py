"""The outputs index (plan 4.1–4.4): the `outputs` table kept in step with `outputs/`.

`Outputs.sync(scope)` rescans one folder (`""` = everything, `<service>`, or
`<service>/<date>`) and applies the difference: new and changed outputs are described and
upserted, vanished ones deleted. The watcher calls it for each folder that changed, with
`pending` so an entry is indexed only once its sizes are stable; startup calls
`reconcile()`, which publishes no event per file. One lock serializes every change, so a
delete never races a rescan.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import sqlite3
import time
from pathlib import Path, PurePosixPath
from typing import Any

from utils.db import Database
from utils.events import EventBus
from utils.outputs import media, trash
from utils.outputs.describe import describe
from utils.outputs.entries import KINDS, kind_of, subtype_of, walk
from utils.paths import Paths

log = logging.getLogger("aihub.outputs")

COLUMNS = ("id", "service", "kind", "title", "path", "is_dir", "main", "preview", "size_bytes", "created_ts",
           "duration_s", "width", "height", "meta", "files", "search", "sig")
CHUNK = 25  # outputs described per lock hold during the startup reconcile
PREVIEW_JOBS = 2  # previews generated at once


class OutputError(Exception):
    def __init__(self, status: int, code: str, detail: str, data: dict[str, Any] | None = None) -> None:
        super().__init__(detail)
        self.status, self.code, self.detail, self.data = status, code, detail, data


def not_found(oid: str) -> OutputError:
    return OutputError(404, "output_not_found", f'No output "{oid}"')


def _under(scope: str) -> tuple[str, list[Any]]:
    if not scope:
        return "1", []
    esc = scope.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return "path LIKE ? ESCAPE '\\'", [esc + "/%"]


def _like(word: str) -> str:
    return "%" + word.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


class Outputs:
    def __init__(self, paths: Paths, db: Database, bus: EventBus, activity: Any = None) -> None:
        self.paths = paths
        self.dir = paths.outputs
        self.prefix = paths.rel(paths.outputs)
        self.db = db
        self.bus = bus
        self.activity = activity
        self.announcer: Any = None  # announce.Announcer, set by the watcher
        self.lock = asyncio.Lock()
        self._preview_jobs = asyncio.Semaphore(PREVIEW_JOBS)
        self._preview_locks: dict[str, asyncio.Lock] = {}
        self._preview_failed: dict[str, str] = {}  # id → sig that failed; retried when the file changes
        self._warm: asyncio.Queue[str] = asyncio.Queue()
        self._warm_task: asyncio.Task[None] | None = None

    # lifecycle --------------------------------------------------------------

    def start(self) -> None:
        self._warm_task = asyncio.create_task(self._warm_loop(), name="aihub-output-previews")

    async def close(self) -> None:
        if self._warm_task:
            self._warm_task.cancel()
            await asyncio.gather(self._warm_task, return_exceptions=True)

    # views -----------------------------------------------------------------

    def view(self, row: dict[str, Any]) -> dict[str, Any]:
        """A row → the brief's `Output`."""
        files = json.loads(row["files"]) if isinstance(row["files"], str) else row["files"]
        oid = row["id"]
        v: dict[str, Any] = {
            "id": oid, "service": row["service"], "kind": row["kind"], "title": row["title"],
            "path": f"{self.prefix}/{row['path']}",
            "files": [{**f, "path": f"{self.prefix}/{f['path']}"} for f in files],
            "url": f"/api/outputs/{oid}/file",
            "preview": f"/api/outputs/{oid}/preview?v={hashlib.sha1(row['sig'].encode()).hexdigest()[:8]}" if row["preview"] else None,
            "size_bytes": row["size_bytes"], "created_ts": row["created_ts"],
            "meta": json.loads(row["meta"]) if isinstance(row["meta"], str) else row["meta"],
        }
        if row["kind"] in ("text", "document") and row["main"] and (sub := subtype_of(row["main"])):
            v["subtype"] = sub
        if row["duration_s"] is not None:
            v["duration_s"] = row["duration_s"]
        if row["width"] and row["height"]:
            v["dims"] = {"w": row["width"], "h": row["height"]}
        return v

    async def row(self, oid: str) -> dict[str, Any]:
        r = await self.db.fetchone("SELECT * FROM outputs WHERE id = ?", (oid,))
        if r is None:
            raise not_found(oid)
        return r

    async def get(self, oid: str) -> dict[str, Any]:
        return self.view(await self.row(oid))

    async def list(
        self, service: str | None = None, kind: str | None = None, q: str | None = None,
        from_ts: float | None = None, to_ts: float | None = None, cursor: str | None = None, limit: int = 60,
    ) -> dict[str, Any]:
        services = [s for s in (service or "").split(",") if s]
        kinds = [k for k in (kind or "").split(",") if k]
        for k in kinds:
            if k not in KINDS:
                raise OutputError(422, "invalid_request", f"kind: {k!r} is not one of {', '.join(KINDS)}")
        after: tuple[float, str] | None = None
        if cursor:
            try:
                ts, _, cid = cursor.rpartition(":")
                after = (float(ts), cid)
            except ValueError:
                raise OutputError(422, "invalid_request", f"cursor: {cursor!r} is not a cursor from this list") from None

        def where(skip: str | None = None) -> tuple[str, list[Any]]:
            cl: list[str] = []
            args: list[Any] = []
            if services and skip != "service":
                cl.append(f"service IN ({','.join('?' * len(services))})")
                args += services
            if kinds and skip != "kind":
                cl.append(f"kind IN ({','.join('?' * len(kinds))})")
                args += kinds
            for word in (q or "").lower().split():
                cl.append("search LIKE ? ESCAPE '\\'")
                args.append(_like(word))
            if from_ts is not None:
                cl.append("created_ts >= ?")
                args.append(from_ts)
            if to_ts is not None:
                cl.append("created_ts <= ?")
                args.append(to_ts)
            return (" AND ".join(cl) or "1"), args

        def run() -> dict[str, Any]:
            w, args = where()
            page_sql, page_args = w, list(args)
            if after:
                page_sql += " AND (created_ts < ? OR (created_ts = ? AND id < ?))"
                page_args += [after[0], after[0], after[1]]
            rows = self.db.fetchall_sync(
                f"SELECT * FROM outputs WHERE {page_sql} ORDER BY created_ts DESC, id DESC LIMIT ?", [*page_args, limit + 1]
            )
            tot = self.db.fetchone_sync(f"SELECT COUNT(*) AS n, COALESCE(SUM(size_bytes), 0) AS b FROM outputs WHERE {w}", args)
            wk, ak = where("kind")
            ws, as_ = where("service")
            by_kind = {r["kind"]: r["n"] for r in self.db.fetchall_sync(f"SELECT kind, COUNT(*) AS n FROM outputs WHERE {wk} GROUP BY kind", ak)}
            by_service = {r["service"]: r["n"] for r in self.db.fetchall_sync(f"SELECT service, COUNT(*) AS n FROM outputs WHERE {ws} GROUP BY service", as_)}
            more = len(rows) > limit
            rows = rows[:limit]
            nxt = f"{rows[-1]['created_ts']!r}:{rows[-1]['id']}" if more and rows else None
            return {"items": [self.view(r) for r in rows], "next_cursor": nxt,
                    "totals": {"count": tot["n"], "size_bytes": tot["b"], "by_kind": by_kind, "by_service": by_service}}

        return await asyncio.to_thread(run)

    # keeping the index in step ---------------------------------------------

    async def _rows_under(self, scope: str) -> dict[str, dict[str, Any]]:
        w, args = _under(scope)
        return {r["path"]: r for r in await self.db.fetchall(f"SELECT id, path, sig, title FROM outputs WHERE {w}", args)}

    @staticmethod
    def _apply(c: sqlite3.Connection, upserts: list[dict[str, Any]], deletes: list[str]) -> None:
        if upserts:
            cols = ", ".join(COLUMNS)
            sets = ", ".join(f"{k} = excluded.{k}" for k in COLUMNS if k != "id")
            c.executemany(
                f"INSERT INTO outputs ({cols}) VALUES ({', '.join('?' * len(COLUMNS))}) ON CONFLICT(id) DO UPDATE SET {sets}",
                [tuple(r[k] for k in COLUMNS) for r in upserts],
            )
        if deletes:
            c.executemany("DELETE FROM outputs WHERE id = ?", [(i,) for i in deletes])

    async def sync(self, scope: str = "", *, publish: bool = True, pending: dict[str, tuple[str, float]] | None = None,
                   stable_s: float = 0.0) -> bool:
        """Rescan `scope` and apply the difference. With `pending` (rel → (sig, first seen)), a
        new or changed output is indexed only once its sig has held for `stable_s`. Returns
        True while something is still settling (call again after `stable_s`)."""
        async with self.lock:
            found = await asyncio.to_thread(walk, self.dir, scope)
            rows = await self._rows_under(scope)
            removed = [r for p, r in rows.items() if p not in found]
            changed = [f for p, f in found.items() if p not in rows or rows[p]["sig"] != f.sig]
            settling = False
            if pending is not None:
                ready, now = [], time.monotonic()
                for f in changed:
                    sig, since = pending.get(f.rel, (None, now))
                    if sig == f.sig and now - since >= stable_s:
                        ready.append(f)
                        pending.pop(f.rel)
                    else:
                        if sig != f.sig:
                            pending[f.rel] = (f.sig, now)
                        settling = True
                w = scope + "/" if scope else ""
                for k in [k for k in pending if k.startswith(w) and k not in found]:
                    del pending[k]
                changed = ready
            described = await asyncio.to_thread(lambda: [r for f in changed if (r := describe(self.dir, f))])
            await self.db.write(lambda c: self._apply(c, described, [r["id"] for r in removed]))
        if publish:
            for r in described:
                v = self.view(r)
                self.bus.publish({"type": "output", "output": v})
                if r["path"] not in rows and self.announcer:
                    self.announcer.add(v)
            for r in removed:
                self.bus.publish({"type": "output_deleted", "id": r["id"]})
        self._queue_previews(described)
        return settling

    async def ingest(self, rel: str) -> dict[str, Any]:
        """Index the output at `rel` now (an upload just written) instead of waiting for the watcher."""
        scope = str(PurePosixPath(rel).parent)
        await self.sync(scope)
        row = (await self._rows_under(scope)).get(rel)
        if row is None:
            raise OutputError(500, "upload_not_indexed", f'"{rel}" was saved but isn\'t an output')
        return await self.get(row["id"])

    async def reconcile(self) -> int:
        """Startup: bring the whole index in line with the disk, in chunks, without an event per
        output. Open pages are told to refetch (`output_deleted` with id `*`) if anything changed."""
        async with self.lock:
            found = await asyncio.to_thread(walk, self.dir, "")
            rows = await self._rows_under("")
            removed = [r["id"] for p, r in rows.items() if p not in found]
            if removed:
                await self.db.write(lambda c: self._apply(c, [], removed))
        changed = [f for p, f in found.items() if p not in rows or rows[p]["sig"] != f.sig]
        done = 0
        for i in range(0, len(changed), CHUNK):
            part = changed[i:i + CHUNK]
            async with self.lock:
                described = await asyncio.to_thread(lambda: [r for f in part if (r := describe(self.dir, f))])
                await self.db.write(lambda c: self._apply(c, described, []))
            done += len(described)
            self._queue_previews(described)
        if removed or done:
            log.info("outputs: indexed %d, removed %d", done, len(removed))
            self.bus.publish({"type": "output_deleted", "id": "*"})
        return done + len(removed)

    # deleting ----------------------------------------------------------------

    async def delete(self, oid: str) -> None:
        """Move the output (file, sidecar and preview, or the whole folder) to `outputs/.trash/`."""
        async with self.lock:
            row = await self.row(oid)
            target = self.dir / row["path"]
            parts = PurePosixPath(row["path"]).parts
            if len(parts) < 2 or ".." in parts or not target.resolve().is_relative_to(self.dir.resolve()):
                raise OutputError(409, "output_not_deletable", f"{self.prefix}/{row['path']} is outside {self.prefix}/ (a symlink?); delete it there")
            if target.exists() or target.is_symlink():
                await asyncio.to_thread(trash.move, self.dir, row["path"], bool(row["is_dir"]))
            await self.db.write(lambda c: self._apply(c, [], [oid]))
        self._preview_failed.pop(oid, None)
        self.bus.publish({"type": "output_deleted", "id": oid})
        if self.activity:
            await self.activity.add(f'Moved "{row["title"]}" to the outputs trash', row["service"], "info")

    # files -------------------------------------------------------------------

    def _safe(self, rel: str | None, oid: str) -> Path:
        if not rel:
            raise OutputError(404, "output_not_found", f'Output "{oid}" has no such file')
        p = self.dir / rel
        if not p.is_file():
            raise OutputError(404, "output_not_found", f"{self.prefix}/{rel} is gone")
        return p

    async def file(self, oid: str, sub: str | None = None) -> Path:
        """The main file, or `sub` (a path inside a folder output, as listed in its files)."""
        row = await self.row(oid)
        if sub is None:
            return self._safe(row["main"], oid)
        listed = {f["path"] for f in json.loads(row["files"])}
        rel = f"{row['path']}/{sub}" if row["is_dir"] else None
        if rel not in listed:
            raise OutputError(404, "output_not_found", f'Output "{oid}" has no file {sub!r}')
        return self._safe(rel, oid)

    async def preview(self, oid: str) -> Path:
        row = await self.row(oid)
        rel = row["preview"]
        if not rel:
            raise OutputError(404, "output_not_found", f'Output "{oid}" has no preview')
        p = self.dir / rel
        if not (p.name.startswith(".") and p.name.endswith(".preview.jpg")):
            return self._safe(rel, oid)  # the image itself, or the 3D job's preview.png
        src = self._safe(row["main"], oid)
        try:
            if p.stat().st_mtime >= src.stat().st_mtime:
                return p
        except OSError:
            pass
        out = None
        if self._preview_failed.get(oid) != row["sig"]:
            lock = self._preview_locks.setdefault(oid, asyncio.Lock())
            async with lock, self._preview_jobs:
                out = await asyncio.to_thread(media.make_preview, src, kind_of(src.name))
            self._preview_locks.pop(oid, None)
            if out is None:
                self._preview_failed[oid] = row["sig"]
        if out is not None:
            return out
        if kind_of(src.name) == "image":
            return src  # can't shrink it: the original still works as a thumbnail
        raise OutputError(404, "output_not_found", f'No preview for output "{oid}"')

    def _queue_previews(self, rows: list[dict[str, Any]]) -> None:
        for r in rows:
            if r["preview"] and PurePosixPath(r["preview"]).name.startswith("."):
                self._warm.put_nowait(r["id"])

    async def _warm_loop(self) -> None:
        """Make previews ahead of the first request, one at a time."""
        while True:
            oid = await self._warm.get()
            try:
                await self.preview(oid)
            except OutputError:
                pass
            except Exception:  # noqa: BLE001: keep warming the rest
                log.exception("preview for %s", oid)
