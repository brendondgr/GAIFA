"""Instances as transient systemd user units (``lcpp-<name>.service``).

Why not child processes of the daemon: a daemon restart or upgrade would kill
every running model. As transient units they are owned by the user manager,
not by lcppd; the daemon rediscovers them on start (see Supervisor.reconcile).
Transient units also vanish on reboot, which is what guarantees no model is
loaded at boot.

Units are started without ``--collect`` so a *failed* one stays around for
its result code; a cleanly stopped one is garbage-collected by systemd.
Logs are read per invocation ID, so a reused instance name never shows the
previous run's output.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path
from typing import AsyncIterator

from lcpp.backends.base import Launched, LogLine, UnitStatus

PREFIX = "lcpp-"


def unit_name(name: str) -> str:
    return f"{PREFIX}{name}.service"


def _run(*args: str, check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(args), capture_output=True, text=True, check=check, timeout=60)


def _journal_line(raw: str) -> LogLine | None:
    try:
        entry = json.loads(raw)
    except json.JSONDecodeError:
        return None
    msg = entry.get("MESSAGE")
    if isinstance(msg, list):  # journald sends non-UTF-8 messages as byte arrays
        msg = bytes(msg).decode("utf-8", errors="replace")
    if msg is None:
        return None
    ts = int(entry.get("__REALTIME_TIMESTAMP", 0)) / 1e6
    prio = int(entry.get("PRIORITY", 6))
    return {"ts": ts, "text": str(msg), "stream": "stderr" if prio <= 4 else "stdout"}


class SystemdBackend:
    def launch(self, name: str, argv: list[str], env: dict[str, str], cwd: Path) -> Launched:
        unit = unit_name(name)
        _run("systemctl", "--user", "reset-failed", unit)
        cmd = [
            "systemd-run", "--user", f"--unit={unit}", f"--description=lcpp instance {name}",
            f"--working-directory={cwd}",
            "--property=KillMode=control-group", "--property=TimeoutStopSec=20",
            *[f"--setenv={k}={v}" for k, v in env.items()],
            "--", *argv,
        ]
        proc = _run(*cmd)
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or proc.stdout).strip() or "systemd-run failed")
        st = self._show(unit)
        pid = int(st.get("MainPID") or 0) or None
        return Launched(pid=pid, invocation=st.get("InvocationID") or None)

    def _show(self, unit: str) -> dict[str, str]:
        out = _run("systemctl", "--user", "show", unit, "-p",
                   "LoadState,ActiveState,MainPID,InvocationID,Result,ExecMainStatus,ExecMainCode").stdout
        return dict(line.split("=", 1) for line in out.splitlines() if "=" in line)

    def status(self, name: str) -> UnitStatus:
        st = self._show(unit_name(name))
        if st.get("LoadState") == "not-found":
            return UnitStatus(active=False)
        active = st.get("ActiveState") in ("active", "activating", "reloading")
        pid = int(st.get("MainPID") or 0) or None
        status = st.get("ExecMainStatus")
        return UnitStatus(active=active, pid=pid if active else None,
                          result=None if active else st.get("Result"),
                          exit_status=int(status) if status and status.isdigit() else None)

    def stop(self, name: str) -> None:
        unit = unit_name(name)
        _run("systemctl", "--user", "stop", unit)
        self.reset(name)

    def reset(self, name: str) -> None:
        _run("systemctl", "--user", "reset-failed", unit_name(name))

    def active_names(self) -> list[str]:
        out = _run("systemctl", "--user", "list-units", "--type=service", "--all", "--plain",
                   "--no-legend", "--state=active,activating", f"{PREFIX}*.service").stdout
        names = []
        for line in out.splitlines():
            unit = line.split()[0] if line.split() else ""
            if unit.startswith(PREFIX) and unit.endswith(".service"):
                names.append(unit[len(PREFIX):-len(".service")])
        return names

    def _journal_args(self, name: str, invocation: str | None) -> list[str]:
        match = f"_SYSTEMD_INVOCATION_ID={invocation}" if invocation else f"--user-unit={unit_name(name)}"
        return ["journalctl", "--user", match, "-o", "json", "--no-pager", "-q"]

    def logs(self, name: str, invocation: str | None, lines: int) -> list[LogLine]:
        out = _run(*self._journal_args(name, invocation), "-n", str(lines)).stdout
        return [ln for ln in map(_journal_line, out.splitlines()) if ln]

    async def follow(self, name: str, invocation: str | None) -> AsyncIterator[LogLine]:
        proc = await asyncio.create_subprocess_exec(
            *self._journal_args(name, invocation), "-f", "-n", "0",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        try:
            assert proc.stdout is not None
            async for raw in proc.stdout:
                line = _journal_line(raw.decode("utf-8", errors="replace"))
                if line:
                    yield line
        finally:
            if proc.returncode is None:
                proc.kill()
                await proc.wait()
