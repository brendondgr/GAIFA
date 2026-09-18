from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator, Protocol, TypedDict


class LogLine(TypedDict):
    ts: float
    text: str
    stream: str


@dataclass
class Launched:
    pid: int | None
    invocation: str | None


@dataclass
class UnitStatus:
    active: bool
    pid: int | None = None
    # "exit-code", "signal", "success"... when the process has ended.
    result: str | None = None
    exit_status: int | None = None


class Backend(Protocol):
    def launch(self, name: str, argv: list[str], env: dict[str, str], cwd: Path) -> Launched: ...

    def status(self, name: str) -> UnitStatus: ...

    def stop(self, name: str) -> None: ...

    def reset(self, name: str) -> None: ...

    def active_names(self) -> list[str]: ...

    def logs(self, name: str, invocation: str | None, lines: int) -> list[LogLine]: ...

    def follow(self, name: str, invocation: str | None) -> AsyncIterator[LogLine]: ...
