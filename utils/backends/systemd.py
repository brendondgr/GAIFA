"""Mods as transient systemd user units, `aihub-<id>.service` (architecture §2, §5).

Ported from lcpp's backend. Units belong to the user manager, not the hub,
so a hub restart leaves mods running and the hub adopts them on start
(`list_ours`). Transient units vanish on reboot. They are started without
`--collect`, so a failed one stays around long enough to read its result;
`start` clears a stale failed unit with the same name first.

Logs come from the journal for the unit, which includes systemd's own lines
("Main process exited, code=exited, status=1").
"""

from __future__ import annotations

import asyncio
import json
import shutil
from collections.abc import AsyncIterator

from utils.backends.base import BackendError, LogLine, UnitState
from utils.manifest import LaunchSpec

PREFIX = "aihub-"
SHOW = "LoadState,ActiveState,SubState,MainPID,ExecMainStartTimestamp,Result,ExecMainCode,ExecMainStatus,ControlGroup"
CALL_TIMEOUT_S = 30


def available() -> bool:
    """True when a systemd user manager answers (not in a bare container or CI)."""
    import subprocess

    if not shutil.which("systemctl") or not shutil.which("systemd-run"):
        return False
    try:
        r = subprocess.run(["systemctl", "--user", "show", "-p", "Version"], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return r.returncode == 0 and r.stdout.startswith("Version=")


async def _run(*args: str, timeout: float = CALL_TIMEOUT_S) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, stdin=asyncio.subprocess.DEVNULL
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        raise BackendError(f"{args[0]} {args[1] if len(args) > 1 else ''} timed out after {timeout:.0f}s") from None
    return proc.returncode or 0, out.decode(errors="replace"), err.decode(errors="replace")


def journal_line(raw: str | bytes) -> LogLine | None:
    try:
        entry = json.loads(raw)
    except ValueError:
        return None
    msg = entry.get("MESSAGE")
    if isinstance(msg, list):  # journald sends non-UTF-8 messages as byte arrays
        msg = bytes(msg).decode("utf-8", errors="replace")
    if msg is None:
        return None
    try:
        ts = int(entry.get("__REALTIME_TIMESTAMP", 0)) / 1e6
        prio = int(entry.get("PRIORITY", 6))
    except (TypeError, ValueError):
        ts, prio = 0.0, 6
    return {"ts": ts, "text": str(msg).rstrip("\n"), "stream": "stderr" if prio <= 4 else "stdout"}


def _ts(value: str) -> float | None:
    # `--timestamp=unix` prints "@1791142365"; empty or "n/a" when unset.
    value = value.strip()
    if value.startswith("@"):
        try:
            return float(value[1:])
        except ValueError:
            return None
    return None


def _int(value: str | None) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except ValueError:
        return None


class SystemdBackend:
    name = "systemd"

    def __init__(self, prefix: str = PREFIX) -> None:
        self.prefix = prefix  # tests use their own, so they never touch real mods

    def unit(self, service_id: str) -> str:
        return f"{self.prefix}{service_id}.service"

    async def start(self, spec: LaunchSpec) -> UnitState:
        unit = self.unit(spec.id)
        await _run("systemctl", "--user", "reset-failed", unit)
        cmd = [
            "systemd-run", "--user", f"--unit={unit}", f"--description=AIHub mod {spec.id}",
            f"--working-directory={spec.cwd}",
            "--property=KillMode=mixed",
            f"--property=TimeoutStopSec={max(1, round(spec.stop_timeout_s))}",
            *[f"--setenv={k}={v}" for k, v in spec.env.items()],
            "--", *spec.argv,
        ]
        rc, out, err = await _run(*cmd)
        if rc != 0:
            raise BackendError((err or out).strip() or f"systemd-run exited with {rc}")
        return await self.state(spec.id)

    async def _show(self, unit: str) -> dict[str, str]:
        rc, out, err = await _run("systemctl", "--user", "show", unit, "--timestamp=unix", "-p", SHOW)
        if rc != 0:
            raise BackendError(err.strip() or f"systemctl show {unit} failed")
        return dict(line.split("=", 1) for line in out.splitlines() if "=" in line)

    async def state(self, service_id: str) -> UnitState:
        st = await self._show(self.unit(service_id))
        if st.get("LoadState") == "not-found":
            return UnitState("inactive")
        active = st.get("ActiveState", "inactive")
        status = _int(st.get("ExecMainStatus"))
        if active in ("active", "activating", "deactivating", "reloading"):
            return UnitState("active", pid=_int(st.get("MainPID")) or None, started_ts=_ts(st.get("ExecMainStartTimestamp", "")))
        result = st.get("Result") or None
        if active == "failed":
            return UnitState("failed", result=result, exit_status=status)
        return UnitState("inactive", result=result, exit_status=status)

    async def workdir(self, service_id: str) -> str | None:
        rc, out, _ = await _run("systemctl", "--user", "show", self.unit(service_id), "-p", "WorkingDirectory", "--value")
        return out.strip() or None if rc == 0 else None

    async def stop(self, service_id: str, timeout: float) -> None:
        unit = self.unit(service_id)
        # TimeoutStopSec was set at start; `stop` blocks until the unit is down.
        await _run("systemctl", "--user", "stop", unit, timeout=timeout + 15)
        await _run("systemctl", "--user", "reset-failed", unit)

    async def list_ours(self) -> list[str]:
        rc, out, _ = await _run(
            "systemctl", "--user", "list-units", "--type=service", "--all", "--plain", "--no-legend",
            "--state=active,activating,deactivating,reloading", f"{self.prefix}*.service",
        )
        ids = []
        for line in out.splitlines():
            unit = line.split()[0] if line.split() else ""
            if unit.startswith(self.prefix) and unit.endswith(".service"):
                ids.append(unit[len(self.prefix):-len(".service")])
        return sorted(ids)

    def _journal(self, service_id: str) -> list[str]:
        return ["journalctl", "--user", "-u", self.unit(service_id), "-o", "json", "--no-pager", "-q"]

    async def logs(self, service_id: str, n: int) -> list[LogLine]:
        _, out, _ = await _run(*self._journal(service_id), "-n", str(max(1, n)))
        return [ln for ln in map(journal_line, out.splitlines()) if ln]

    async def follow(self, service_id: str) -> AsyncIterator[LogLine]:
        proc = await asyncio.create_subprocess_exec(
            *self._journal(service_id), "-f", "-n", "0",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, stdin=asyncio.subprocess.DEVNULL,
        )
        try:
            assert proc.stdout is not None
            async for raw in proc.stdout:
                line = journal_line(raw)
                if line:
                    yield line
        finally:
            if proc.returncode is None:
                proc.kill()
                await proc.wait()

    async def close(self) -> None:
        """Units outlive the hub on purpose."""
