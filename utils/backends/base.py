"""What every backend provides. The hub only talks to mods' processes through this."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal, Protocol, TypedDict

from utils.manifest import LaunchSpec

UnitActive = Literal["active", "inactive", "failed"]


class LogLine(TypedDict):
    ts: float
    text: str
    stream: Literal["stdout", "stderr"]


@dataclass
class UnitState:
    """A mod process as the backend sees it."""

    active: UnitActive
    pid: int | None = None
    started_ts: float | None = None
    # Once it has ended: how ("exit-code", "signal", "timeout", ...) and the exit status.
    result: str | None = None
    exit_status: int | None = None

    def describe_exit(self) -> str:
        if self.result in (None, "success") and not self.exit_status:
            return "exited"
        if self.result == "signal" and self.exit_status:
            return f"killed by signal {self.exit_status}"
        if self.exit_status is not None:
            return f"exited with status {self.exit_status}"
        return f"ended ({self.result})"


class BackendError(RuntimeError):
    """The backend couldn't do what was asked (systemd-run failed, the executable is missing...)."""


class Backend(Protocol):
    name: str

    async def start(self, spec: LaunchSpec) -> UnitState:
        """Launch the mod. Raises BackendError when it can't be launched at all."""
        ...

    async def stop(self, service_id: str, timeout: float) -> None:
        """SIGTERM, then SIGKILL after `timeout`. Stopping something that isn't running is fine."""
        ...

    async def state(self, service_id: str) -> UnitState: ...

    async def list_ours(self) -> list[str]:
        """Ids of the mods this backend has running (for adoption on hub start)."""
        ...

    async def logs(self, service_id: str, n: int) -> list[LogLine]:
        """The last `n` lines, oldest first."""
        ...

    def follow(self, service_id: str) -> AsyncIterator[LogLine]:
        """New lines as they arrive, until the consumer stops iterating."""
        ...

    async def close(self) -> None:
        """Called when the hub stops."""
        ...
