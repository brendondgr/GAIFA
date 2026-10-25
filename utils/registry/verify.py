"""Checksums (plan 3.3): `POST /api/models/{id}/verify` queues a model; one worker hashes
one model at a time in a thread, in 8 MB reads, and publishes `model` events with
`progress` about once a second.

The first verify of a file records its sha256; later ones compare against it and
flag `checksum_mismatch` (storing what was found as `actual_sha256`). `reset=True`
forgets the recorded checksums and records new ones. Shutdown stops the hashing
thread within one read.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import threading
from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING, Any

from utils.registry.model import RegistryError, now_iso

if TYPE_CHECKING:
    from utils.registry.store import Registry

log = logging.getLogger("gaifa.registry")

CHUNK = 8 * 1024 * 1024
HASH = hashlib.sha256
PROGRESS_EVERY_S = 1.0


class Cancelled(Exception):
    pass


class Verifier:
    def __init__(self, reg: Registry, progress_every_s: float = PROGRESS_EVERY_S) -> None:
        self.reg = reg
        self.every = progress_every_s
        self.queue: deque[tuple[str, bool]] = deque()
        self.current: str | None = None
        self._stop = threading.Event()  # set to stop the running hash (cancel or shutdown)
        self._wake = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        reg.verifier = self
        reg.on_delete = self.cancel  # type: ignore[method-assign]

    def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="gaifa-verify")

    async def close(self) -> None:
        self._stop.set()
        self.queue.clear()
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        self.reg.progress.clear()

    def request(self, model_id: str, reset: bool = False) -> dict[str, Any]:
        reg = self.reg
        e = reg.entry(model_id)
        if model_id in reg.progress:
            return reg.view(model_id, e)  # already queued or running
        if reg.readonly:
            raise RegistryError(409, "registry_invalid", reg.readonly)
        view = reg.view(model_id, e)
        if not any(f["exists"] for f in view["files"]):
            raise RegistryError(409, "model_files_missing", f"{e.name}: its files are missing, so there is nothing to verify")
        reg.progress[model_id] = 0.0
        self.queue.append((model_id, reset))
        self._wake.set()
        reg.publish(model_id)
        return reg.view(model_id)

    def cancel(self, model_id: str) -> None:
        self.queue = deque(x for x in self.queue if x[0] != model_id)
        if self.current == model_id:
            self._stop.set()
        self.reg.progress.pop(model_id, None)

    async def _run(self) -> None:
        while True:
            while not self.queue:
                self._wake.clear()
                await self._wake.wait()
            model_id, reset = self.queue.popleft()
            self.current = model_id
            self._stop = threading.Event()
            try:
                await self._verify(model_id, reset)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001: one bad model must not stop the queue
                log.exception("verifying %s failed", model_id)
            finally:
                self.current = None
                if self.reg.progress.pop(model_id, None) is not None:
                    self.reg.publish(model_id)

    async def _verify(self, model_id: str, reset: bool) -> None:
        reg = self.reg
        e = reg.entries.get(model_id)
        if e is None:
            return
        todo: list[tuple[str, Path, int]] = []
        for f in e.files:
            p = reg.abs(f.path)  # reading through a symlinked folder is fine; only deletes stay inside
            try:
                st = p.stat()
            except OSError:
                continue
            if p.is_file():
                todo.append((f.path, p, st.st_size))
        total = sum(size for _, _, size in todo) or 1
        done = [0]
        stop = self._stop
        fut = asyncio.ensure_future(asyncio.to_thread(_hash_all, todo, done, stop))
        while True:
            finished, _ = await asyncio.wait({fut}, timeout=self.every)
            if finished:
                break
            if model_id in reg.progress:
                reg.progress[model_id] = min(done[0] / total, 0.999)
                reg.publish(model_id)
        try:
            results = fut.result()
        except Cancelled:
            return
        await self._apply(model_id, results, reset)

    async def _apply(self, model_id: str, results: dict[str, tuple[str | None, int | None, str | None]], reset: bool) -> None:
        reg = self.reg
        reg.refresh()
        e = reg.entries.get(model_id)
        if e is None or model_id not in reg.progress:
            return  # deleted (or cancelled) meanwhile
        now = now_iso()
        mismatched, failed = [], []
        if not results:
            failed.append("no files could be read")
        for f in e.files:
            if f.path not in results:
                continue
            sha, size, err = results[f.path]
            if sha is None:
                failed.append(f"{f.path}: {err}")
                continue
            if f.sha256 is None or reset:
                f.sha256, f.size_bytes, f.verified_at, f.actual_sha256 = sha, size, now, None
            elif f.sha256 == sha:
                f.verified_at, f.actual_sha256 = now, None
                if f.size_bytes is None:
                    f.size_bytes = size
            else:
                f.actual_sha256 = sha
                mismatched.append(f.path)
        reg.progress.pop(model_id, None)
        reg.save()
        reg.publish(model_id)
        if reg.activity:
            if mismatched:
                await reg.activity.add(f"Checksum mismatch: {e.name} ({', '.join(Path(p).name for p in mismatched)})", level="error", route=f"#/models/{model_id}")
            elif failed:
                await reg.activity.add(f"Couldn't verify all of {e.name}: {'; '.join(failed)}", level="warn", route=f"#/models/{model_id}")
            else:
                await reg.activity.add(f"Verified {e.name}", route=f"#/models/{model_id}")
        reg.changed(model_id)


def _hash_all(todo: list[tuple[str, Path, int]], done: list[int], stop: threading.Event) -> dict[str, tuple[str | None, int | None, str | None]]:
    """{rel path: (sha256, size, None) or (None, None, why)}. Runs in a thread."""
    out: dict[str, tuple[str | None, int | None, str | None]] = {}
    buf = bytearray(CHUNK)
    view = memoryview(buf)
    for rel, p, size in todo:
        h = HASH()
        read = 0
        try:
            with open(p, "rb", buffering=0) as fh:
                while True:
                    if stop.is_set():
                        raise Cancelled
                    n = fh.readinto(view)
                    if not n:
                        break
                    h.update(view[:n])
                    read += n
                    done[0] += n
            now = p.stat().st_size
        except OSError as e:
            out[rel] = (None, None, e.strerror or str(e))
            continue
        if read != now:
            out[rel] = (None, None, "changed while it was being read")
            continue
        out[rel] = (h.hexdigest(), read, None)
    return out
