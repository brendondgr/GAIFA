"""Instances as plain child processes, logging to files. Tests and dev only:
children die with the daemon, unlike the systemd backend."""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import time
import uuid
from pathlib import Path
from typing import AsyncIterator

from lcpp.backends.base import Launched, LogLine, UnitStatus


class SubprocessBackend:
    def __init__(self, log_dir: Path):
        self.log_dir = log_dir
        self.procs: dict[str, subprocess.Popen[bytes]] = {}
        self.invocations: dict[str, str] = {}

    def _log(self, name: str, invocation: str | None) -> Path:
        return self.log_dir / f"{name}.{invocation or self.invocations.get(name, 'none')}.log"

    def launch(self, name: str, argv: list[str], env: dict[str, str], cwd: Path) -> Launched:
        self.log_dir.mkdir(parents=True, exist_ok=True)
        invocation = uuid.uuid4().hex
        self.invocations[name] = invocation
        with open(self._log(name, invocation), "wb") as out:
            proc = subprocess.Popen(argv, cwd=cwd, env={**os.environ, **env}, stdout=out,
                                    stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                    start_new_session=True)
        self.procs[name] = proc
        return Launched(pid=proc.pid, invocation=invocation)

    def status(self, name: str) -> UnitStatus:
        proc = self.procs.get(name)
        if proc is None:
            return UnitStatus(active=False)
        code = proc.poll()
        if code is None:
            return UnitStatus(active=True, pid=proc.pid)
        return UnitStatus(active=False, result="success" if code == 0 else "exit-code",
                          exit_status=code if code >= 0 else 128 - code)

    def stop(self, name: str) -> None:
        proc = self.procs.get(name)
        if proc is None or proc.poll() is not None:
            return
        os.killpg(proc.pid, signal.SIGTERM)
        try:
            proc.wait(10)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()

    def reset(self, name: str) -> None:
        proc = self.procs.get(name)
        if proc is not None and proc.poll() is not None:
            del self.procs[name]

    def active_names(self) -> list[str]:
        return [n for n, p in self.procs.items() if p.poll() is None]

    def logs(self, name: str, invocation: str | None, lines: int) -> list[LogLine]:
        path = self._log(name, invocation)
        if not path.exists():
            return []
        mtime = path.stat().st_mtime
        text = path.read_text(errors="replace").splitlines()[-lines:]
        return [{"ts": mtime, "text": t, "stream": "stderr"} for t in text]

    async def follow(self, name: str, invocation: str | None) -> AsyncIterator[LogLine]:
        path = self._log(name, invocation)
        pos = path.stat().st_size if path.exists() else 0
        while True:
            if path.exists() and path.stat().st_size > pos:
                with open(path, "rb") as f:
                    f.seek(pos)
                    chunk = f.read()
                pos += len(chunk)
                for t in chunk.decode(errors="replace").splitlines():
                    yield {"ts": time.time(), "text": t, "stream": "stderr"}
            await asyncio.sleep(0.2)
