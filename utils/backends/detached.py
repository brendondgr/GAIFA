"""Mods as detached processes that outlive the hub, where there's no systemd (plan 37.1): macOS, or a
Linux without a user manager.

- **Start:** the mod runs in its own session (its own process group), its stdout and stderr go to
  `data/state/hub/pids/<id>.out` (truncated at each start), and `data/state/hub/pids/<id>.json` records
  `{pid, create_time, command_hash, cwd, started_ts, port}`.
- **Adoption:** after a hub restart, a pidfile whose pid still runs with the same start time is the
  mod; any other pidfile is stale and removed.
- **Stop:** like systemd's `KillMode=mixed`: SIGTERM (and SIGCONT) to the main process, then SIGKILL to
  its process group after the timeout.
- **Logs:** `logs` reads the end of the output file and `follow` tails it; the hub's shipper writes
  them on to `data/logs/<id>.log` as for every backend. A mod adopted after a restart has no exit status
  when it ends (it isn't the hub's child): it reads as failed, "gone".
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import signal
import subprocess
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from utils.backends.base import BackendError, LogLine, UnitState
from utils.manifest import LaunchSpec

POLL_S = 0.3
TAIL_BYTES = 256 * 1024


def _ps() -> Any:
    import psutil

    return psutil


def command_hash(argv: list[str]) -> str:
    return hashlib.sha256("\0".join(argv).encode()).hexdigest()[:16]


class DetachedBackend:
    name = "detached"

    def __init__(self, state_dir: Path, poll_s: float = POLL_S) -> None:
        self.dir = Path(state_dir)
        self.poll_s = poll_s
        self._children: dict[str, subprocess.Popen[bytes]] = {}   # started by this hub: reaped, with exit codes
        self._ended: dict[str, UnitState] = {}

    # files -----------------------------------------------------------------------------

    def _pidfile(self, sid: str) -> Path:
        return self.dir / f"{sid}.json"

    def _out(self, sid: str) -> Path:
        return self.dir / f"{sid}.out"

    def _record(self, sid: str) -> dict[str, Any] | None:
        try:
            return json.loads(self._pidfile(sid).read_text())
        except (OSError, ValueError):
            return None

    def _alive(self, rec: dict[str, Any]) -> bool:
        """The recorded process still runs: same pid, same start time (pids get reused)."""
        ps = _ps()
        try:
            p = ps.Process(int(rec["pid"]))
            return abs(p.create_time() - float(rec["create_time"])) < 1.0 and p.status() != ps.STATUS_ZOMBIE
        except (ps.NoSuchProcess, ps.AccessDenied, KeyError, ValueError, TypeError):
            return False

    # the protocol ------------------------------------------------------------------------

    async def start(self, spec: LaunchSpec) -> UnitState:
        rec = self._record(spec.id)
        if rec and self._alive(rec):
            raise BackendError(f"{spec.id} is already running (pid {rec['pid']})")
        if not spec.cwd.is_dir():
            raise BackendError(f"working directory {spec.cwd} does not exist")
        self.dir.mkdir(parents=True, exist_ok=True)
        out = self._out(spec.id).open("wb")
        try:
            proc = subprocess.Popen(spec.argv, cwd=spec.cwd, env={**os.environ, **spec.env}, stdin=subprocess.DEVNULL,
                                    stdout=out, stderr=subprocess.STDOUT, start_new_session=True)
        except (FileNotFoundError, PermissionError, NotADirectoryError) as e:
            out.write(f"can't run {spec.argv[0]}: {e.strerror}\n".encode())
            raise BackendError(f"can't run {spec.argv[0]}: {e.strerror}") from None
        finally:
            out.close()
        try:
            created = _ps().Process(proc.pid).create_time()
        except Exception:  # noqa: BLE001: it exited at once; state() reports how
            created = time.time()
        rec = {"pid": proc.pid, "create_time": created, "command_hash": command_hash(spec.argv), "cwd": str(spec.cwd),
               "started_ts": time.time(), "port": spec.port}
        tmp = self._pidfile(spec.id).with_suffix(".tmp")
        tmp.write_text(json.dumps(rec))
        tmp.replace(self._pidfile(spec.id))
        self._children[spec.id] = proc
        self._ended.pop(spec.id, None)
        return await self.state(spec.id)

    async def state(self, service_id: str) -> UnitState:
        proc = self._children.get(service_id)
        rec = self._record(service_id)
        if proc is not None:
            code = proc.poll()
            if code is None:
                return UnitState("active", pid=proc.pid, started_ts=(rec or {}).get("started_ts"))
            del self._children[service_id]
            self._pidfile(service_id).unlink(missing_ok=True)
            self._ended[service_id] = (UnitState("inactive", result="success", exit_status=0) if code == 0 else
                                       UnitState("failed", result="signal", exit_status=-code) if code < 0 else
                                       UnitState("failed", result="exit-code", exit_status=code))
        elif rec is not None:
            if self._alive(rec):
                return UnitState("active", pid=int(rec["pid"]), started_ts=rec.get("started_ts"))
            self._pidfile(service_id).unlink(missing_ok=True)       # stale: it ended while the hub was away
            self._ended[service_id] = UnitState("failed", result="gone")
        return self._ended.get(service_id, UnitState("inactive"))

    async def stop(self, service_id: str, timeout: float) -> None:
        st = await self.state(service_id)
        self._ended.pop(service_id, None)
        if st.active != "active" or st.pid is None:
            return
        pid = st.pid
        try:
            os.kill(pid, signal.SIGTERM)
            os.kill(pid, signal.SIGCONT)
        except ProcessLookupError:
            pass
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and (await self.state(service_id)).active == "active":
            await asyncio.sleep(0.05)
        try:
            os.killpg(pid, signal.SIGKILL)       # the rest of its group (and it, if it ignored SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
        proc = self._children.pop(service_id, None)
        if proc is not None:
            await asyncio.to_thread(proc.wait)
        self._pidfile(service_id).unlink(missing_ok=True)
        self._ended.pop(service_id, None)       # stopped on purpose: inactive, like systemd after stop

    async def list_ours(self) -> list[str]:
        out = []
        for f in sorted(self.dir.glob("*.json")) if self.dir.is_dir() else []:
            if (await self.state(f.stem)).active == "active":
                out.append(f.stem)
        return out

    async def workdir(self, service_id: str) -> str | None:
        rec = self._record(service_id)
        return rec.get("cwd") if rec else None

    async def pids(self, service_id: str) -> list[int]:
        st = await self.state(service_id)
        return [st.pid] if st.active == "active" and st.pid else []

    async def logs(self, service_id: str, n: int) -> list[LogLine]:
        if n <= 0:
            return []
        try:
            with self._out(service_id).open("rb") as f:
                f.seek(0, os.SEEK_END)
                f.seek(max(0, f.tell() - TAIL_BYTES))
                raw = f.read()
        except OSError:
            return []
        now = time.time()
        return [{"ts": now, "text": line.decode(errors="replace").rstrip("\r"), "stream": "stdout"} for line in raw.split(b"\n")[:-1][-n:]]

    async def follow(self, service_id: str) -> AsyncIterator[LogLine]:
        path = self._out(service_id)
        pos, buf = (path.stat().st_size if path.exists() else 0), b""
        while True:
            try:
                size = path.stat().st_size
                if size < pos:            # truncated: the mod was started again
                    pos, buf = 0, b""
                if size > pos:
                    with path.open("rb") as f:
                        f.seek(pos)
                        chunk = f.read(size - pos)
                    pos += len(chunk)
                    buf += chunk
                    *lines, buf = buf.split(b"\n")
                    for raw in lines:
                        yield {"ts": time.time(), "text": raw.decode(errors="replace").rstrip("\r"), "stream": "stdout"}
            except OSError:
                pass
            await asyncio.sleep(self.poll_s)

    async def close(self) -> None:
        """Mods outlive the hub: nothing is stopped."""
