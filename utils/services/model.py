"""The service model: `Service` (one per mod), `Timing`, `ServiceError` and the state types."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Literal

from utils import manifest as mf

log = logging.getLogger("gaifa.services")

ServiceState = Literal["stopped", "starting", "ready", "degraded", "stopping", "failed"]
LoadState = Literal["unloaded", "loading", "loaded", "unloading", "n/a"]
GB = 1000**3  # decimal GB, as the UI shows it (and config, manifests and status use)
LOG_TAIL = 20


class ServiceError(Exception):
    """Turned into the error envelope by the routes: `HubError(status, code, detail)`."""

    def __init__(self, status: int, code: str, detail: str, data: dict[str, Any] | None = None) -> None:
        super().__init__(detail)
        self.status, self.code, self.detail, self.data = status, code, detail, data


@dataclass
class Timing:
    """Intervals, shortened by tests."""

    start_poll_s: float = 0.5
    health_every_s: float = 5.0
    health_timeout_s: float = 3.0
    degraded_after: int = 2
    failed_after: int = 5
    backoff_s: tuple[float, ...] = (2.0, 4.0, 8.0)
    restart_window_s: float = 300.0
    status_busy_s: float = 2.0
    status_idle_s: float = 10.0


@dataclass
class Service:
    mod: mf.Mod
    eff: mf.Effective
    errors: list[str]  # manifest errors plus config clashes; non-empty = not startable
    state: ServiceState = "stopped"
    state_since: float = field(default_factory=time.time)
    load: LoadState = "n/a"
    idle_s: float | None = None
    busy: bool = False
    stats: list[dict[str, Any]] = field(default_factory=list)
    jobs: list[dict[str, Any]] = field(default_factory=list)
    memory_estimate_gb: float | None = None
    pid: int | None = None
    live_port: int | None = None  # the port of the running process; None while stopped
    started_ts: float | None = None
    command: list[str] = field(default_factory=list)
    health: dict[str, Any] | None = None
    status: dict[str, Any] | None = None
    status_ts: float | None = None
    tools_rev: str | None = None  # the status's `tools_rev` (plan 51.1): a change makes the catalog read its tools again
    load_set_at: float = 0.0  # time.monotonic() when the hub itself last set `load` (a status read started before it is stale)
    operations: list[dict[str, Any]] | None = None  # cached per process start (operations.py)
    operations_key: tuple[Any, ...] | None = None
    operations_ts: float | None = None
    operations_error: str | None = None
    last_error: str | None = None
    start_failed_at: float | None = None   # capability-enablement 1.3: when its last start failed; cleared once ready or stopped
    in_flight: int = 0
    last_request_ts: float | None = None
    misses: int = 0
    restarts: deque[float] = field(default_factory=lambda: deque(maxlen=10))
    gen: int = 0
    gpu_index: int | None = None   # plan 36.3: the GPU the hub started it on (machines with more than one), else None
    tasks: set[asyncio.Task[Any]] = field(default_factory=set)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    @property
    def id(self) -> str:
        return self.mod.id

    @property
    def m(self) -> mf.Manifest | None:
        return self.mod.manifest

    @property
    def external(self) -> bool:
        return bool(self.m and self.m.run.kind == "external")

    @property
    def port(self) -> int:
        """The port it's listening on while running (a config change applies at the next start)."""
        return self.live_port or self.eff.port

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def has_memory(self) -> bool:
        return bool(self.m and self.m.memory)

    @property
    def startable(self) -> bool:
        return not self.errors and self.m is not None

    @property
    def up(self) -> bool:
        return self.state in ("ready", "degraded")


def _why(h: dict[str, Any]) -> str:
    if h.get("status"):
        return f"HTTP {h['status']}"
    if isinstance(h.get("body"), str) and h["body"]:
        return h["body"][:200]
    return "no answer"


def _log_task_error(task: asyncio.Task[Any]) -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None and not isinstance(exc, ServiceError):
        log.error("service task failed", exc_info=exc)
