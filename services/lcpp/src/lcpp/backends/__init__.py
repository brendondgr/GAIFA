"""How instance processes are actually run.

``SystemdBackend`` is the real one: each instance is a transient systemd user
unit, so it outlives daemon restarts, logs to journald, and is killed as a
whole cgroup. ``SubprocessBackend`` exists for tests and foreground dev runs.
"""

from __future__ import annotations

import os

from lcpp.backends.base import Backend, Launched, LogLine, UnitStatus
from lcpp.paths import Paths

__all__ = ["Backend", "Launched", "LogLine", "UnitStatus", "make_backend"]


def make_backend(paths: Paths, kind: str | None = None) -> Backend:
    kind = kind or os.environ.get("LCPP_BACKEND", "systemd")
    if kind == "subprocess":
        from lcpp.backends.subprocess import SubprocessBackend
        return SubprocessBackend(paths.state / "logs")
    from lcpp.backends.systemd import SystemdBackend
    return SystemdBackend()
