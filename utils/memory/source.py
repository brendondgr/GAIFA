"""Where memory numbers come from (plan 5.1–5.2). `ProcSource` reads the machine; tests
inject a fake with the same two methods.

- `collect(mgr)`: each running mod's processes: its unit (the backend's `pids`), its
  `extra_units` (globs, resolved every 10 s), its `containers` (podman, every 10 s), and
  for an external mod without units or containers, whoever listens on its port.
- `read(pids)`: blocking, run in a thread: meminfo, the GPU, and each mod's footprint.
- `available()`: blocking and cheap: MemAvailable now (make-room waits poll it).
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any, Protocol

from utils import proc

if TYPE_CHECKING:
    from utils.services import ServiceManager
    from utils.services.model import Service

RESOLVE_EVERY_S = 10.0


class Source(Protocol):
    async def collect(self, mgr: ServiceManager) -> dict[str, list[int]]: ...

    def read(self, pids: dict[str, list[int]]) -> tuple[dict[str, int], dict[str, Any] | None, dict[str, int]]: ...

    def available(self) -> int: ...


class ProcSource:
    def __init__(self) -> None:
        self._cache: dict[tuple[str, str], tuple[float, list[int]]] = {}  # (kind, name) → (when, pids)

    def _cached(self, key: tuple[str, str]) -> list[int] | None:
        hit = self._cache.get(key)
        return hit[1] if hit and time.monotonic() - hit[0] < RESOLVE_EVERY_S else None

    async def _extra(self, svc: Service) -> list[int]:
        m = svc.m.memory if svc.m else None
        if not m:
            return []
        pids: list[int] = []
        for pattern in m.extra_units:
            got = self._cached(("units", pattern))
            if got is None:
                units = await asyncio.to_thread(proc.units_matching, pattern)
                got = [p for u in units for p in await asyncio.to_thread(proc.unit_pids, u)]
                self._cache[("units", pattern)] = (time.monotonic(), got)
            pids += got
        for name in m.containers:
            got = self._cached(("container", name))
            if got is None:
                pid = await asyncio.to_thread(proc.container_pid, name)
                got = [pid] if pid else []
                self._cache[("container", name)] = (time.monotonic(), got)
            pids += got
        return pids

    async def collect(self, mgr: ServiceManager) -> dict[str, list[int]]:
        out: dict[str, list[int]] = {}
        for svc in mgr.list():
            if svc.state in ("stopped", "failed") and not svc.external:
                continue
            pids: list[int] = []
            if not svc.external:
                try:
                    pids = await mgr.backend.pids(svc.id)
                except Exception:  # noqa: BLE001: a backend hiccup must not stop sampling
                    pids = []
            pids += await self._extra(svc)
            if svc.external and not pids and svc.up:
                key = ("port", str(svc.port))
                got = self._cached(key)
                if got is None:
                    owner = await asyncio.to_thread(proc.port_owner, svc.port)
                    got = [owner["pid"]] if owner and isinstance(owner.get("pid"), int) else []
                    self._cache[key] = (time.monotonic(), got)
                pids = got
            if pids:
                out[svc.id] = sorted(set(pids))
        return out

    def read(self, pids: dict[str, list[int]]) -> tuple[dict[str, int], dict[str, Any] | None, dict[str, int]]:
        return proc.meminfo(), proc.gpu(), {sid: proc.footprint(p) for sid, p in pids.items()}

    def available(self) -> int:
        return proc.meminfo()["available_bytes"]
