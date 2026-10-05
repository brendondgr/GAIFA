"""Mods as child processes of the hub: tests and `python app.py --dev`.

Unlike systemd units, children stop with the hub (`close`). Each runs in its
own process group, and stop follows systemd's `KillMode=mixed`: SIGTERM to
the main process (plus SIGCONT, so a suspended one can act on it), then SIGKILL to the whole group. stdout and stderr go into
a ring buffer per mod, which `logs` and `follow` read.
"""

from __future__ import annotations

import asyncio
import os
import signal
import time
from collections import deque
from collections.abc import AsyncIterator

from utils.backends.base import BackendError, LogLine, UnitState
from utils.manifest import LaunchSpec

RING = 5000
CHUNK = 65536


class _Child:
    def __init__(self, proc: asyncio.subprocess.Process, started_ts: float, cwd: str) -> None:
        self.proc = proc
        self.started_ts = started_ts
        self.cwd = cwd
        self.readers: list[asyncio.Task[None]] = []


class SubprocessBackend:
    name = "subprocess"

    def __init__(self, ring: int = RING) -> None:
        self._children: dict[str, _Child] = {}
        self._logs: dict[str, deque[LogLine]] = {}
        self._followers: dict[str, set[asyncio.Queue[LogLine]]] = {}
        self._ring = ring

    def _emit(self, service_id: str, text: str, stream: str) -> None:
        line: LogLine = {"ts": time.time(), "text": text, "stream": stream}  # type: ignore[typeddict-item]
        self._logs.setdefault(service_id, deque(maxlen=self._ring)).append(line)
        for q in list(self._followers.get(service_id, ())):
            if q.full():  # a stalled follower loses its oldest line rather than blocking the mod
                q.get_nowait()
            q.put_nowait(line)

    async def _read(self, service_id: str, stream: asyncio.StreamReader, name: str) -> None:
        buf = b""
        while True:
            chunk = await stream.read(CHUNK)
            if not chunk:
                break
            buf += chunk
            *lines, buf = buf.split(b"\n")
            for raw in lines:
                self._emit(service_id, raw.rstrip(b"\r").decode(errors="replace"), name)
            if len(buf) > CHUNK:  # a very long line without a newline: emit it in pieces
                self._emit(service_id, buf.decode(errors="replace"), name)
                buf = b""
        if buf:
            self._emit(service_id, buf.decode(errors="replace"), name)

    async def start(self, spec: LaunchSpec) -> UnitState:
        old = self._children.get(spec.id)
        if old and old.proc.returncode is None:
            raise BackendError(f"{spec.id} is already running (pid {old.proc.pid})")
        if not spec.cwd.is_dir():
            raise BackendError(f"working directory {spec.cwd} does not exist")
        try:
            proc = await asyncio.create_subprocess_exec(
                *spec.argv,
                cwd=spec.cwd,
                env={**os.environ, **spec.env},
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )
        except (FileNotFoundError, PermissionError, NotADirectoryError) as e:
            self._emit(spec.id, f"can't run {spec.argv[0]}: {e.strerror}", "stderr")
            raise BackendError(f"can't run {spec.argv[0]}: {e.strerror}") from None
        child = _Child(proc, time.time(), str(spec.cwd))
        assert proc.stdout and proc.stderr
        child.readers = [
            asyncio.create_task(self._read(spec.id, proc.stdout, "stdout")),
            asyncio.create_task(self._read(spec.id, proc.stderr, "stderr")),
        ]
        self._children[spec.id] = child
        return await self.state(spec.id)

    async def state(self, service_id: str) -> UnitState:
        child = self._children.get(service_id)
        if child is None:
            return UnitState("inactive")
        code = child.proc.returncode
        if code is None:
            return UnitState("active", pid=child.proc.pid, started_ts=child.started_ts)
        if code == 0:
            return UnitState("inactive", result="success", exit_status=0)
        if code < 0:
            return UnitState("failed", result="signal", exit_status=-code)
        return UnitState("failed", result="exit-code", exit_status=code)

    async def stop(self, service_id: str, timeout: float) -> None:
        child = self._children.get(service_id)
        if child is None:
            return
        proc = child.proc
        if proc.returncode is None:
            try:
                os.kill(proc.pid, signal.SIGTERM)
                os.kill(proc.pid, signal.SIGCONT)  # like systemd: a suspended process must run to see SIGTERM
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(proc.wait(), timeout)
            except TimeoutError:
                pass
            _killpg(proc.pid)
            await proc.wait()
        else:
            _killpg(proc.pid)  # leftovers of a crashed mod
        for t in child.readers:
            try:
                await asyncio.wait_for(t, 2)
            except (TimeoutError, asyncio.CancelledError):
                t.cancel()
        # Stopped cleanly = inactive, like systemd after `stop` + `reset-failed`.
        del self._children[service_id]

    async def workdir(self, service_id: str) -> str | None:
        child = self._children.get(service_id)
        return child.cwd if child else None

    async def pids(self, service_id: str) -> list[int]:
        child = self._children.get(service_id)
        return [child.proc.pid] if child and child.proc.returncode is None else []

    async def list_ours(self) -> list[str]:
        return sorted(i for i, c in self._children.items() if c.proc.returncode is None)

    async def logs(self, service_id: str, n: int) -> list[LogLine]:
        ring = self._logs.get(service_id)
        return list(ring)[-n:] if ring and n > 0 else []

    async def follow(self, service_id: str) -> AsyncIterator[LogLine]:
        q: asyncio.Queue[LogLine] = asyncio.Queue(1000)
        self._followers.setdefault(service_id, set()).add(q)
        try:
            while True:
                yield await q.get()
        finally:
            self._followers.get(service_id, set()).discard(q)

    async def close(self) -> None:
        """Children don't outlive the hub."""
        await asyncio.gather(*(self.stop(i, 5) for i in list(self._children)), return_exceptions=True)


def _killpg(pid: int) -> None:
    try:
        os.killpg(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
