"""When the GPU is free for background indexing (plan 28.2, decided 2026-10-20): a reading sampled every second
has stayed under `busy_pct` for `idle_s`.

Two measures (`EMBED_IDLE_MEASURE`):
- `aihub` (the default): AIHub's own GPU use, and nothing heavy from outside it. It reads 100 while another
  GPU mod (one with `[memory]`) is busy, has a request in flight or a job running (the hub's `GET
  /api/services`), or while the whole GPU's `gpu_busy_percent` has a median of `device_pct` or more over the last
  `window_s` (someone else's work: a game, a script). Otherwise it is the other mods' `gpu_busy_pct` from `GET
  /api/memory` (the DRM engine counters: Vulkan work such as lcpp's). ROCm compute goes through `/dev/kfd`, which
  neither DRM fdinfo nor this kernel's `/sys/class/kfd/kfd/proc/<pid>` accounts per process (2026-10-20), hence
  the activity signals.
- `device`: the whole GPU's `gpu_busy_percent` median alone. On gfx1151 it sits at 13–17 % with only the desktop
  running and jumps to 80–90 % about every 15 s, so under 10 % it rarely holds; raise the threshold with it.

Our own encoding makes the GPU busy too: samples taken while the encoder works (and for `grace_s` after) are
left out. Between batches the indexer reads again (`busy_now`); any other work then stops indexing and the quiet
period starts over. A machine without the sysfs file counts its device part as idle.
"""

from __future__ import annotations

import glob
import statistics
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

SYSFS = "/sys/class/drm/card*/device/gpu_busy_percent"


def read_busy(pattern: str = SYSFS) -> int | None:
    """The busiest GPU's percentage, or None when there's no such file."""
    best = None
    for p in glob.glob(pattern):
        try:
            v = int(Path(p).read_text().strip())
        except (OSError, ValueError):
            continue
        best = v if best is None else max(best, v)
    return best


class DeviceMedian:
    """`gpu_busy_percent`, as the median of the readings in the last `window_s` (the desktop's spikes don't count)."""

    def __init__(self, window_s: float = 30, read: Callable[[], int | None] = read_busy,
                 clock: Callable[[], float] = time.monotonic):
        self.window_s, self.read, self.clock = window_s, read, clock
        self.samples: list[tuple[float, int]] = []

    def __call__(self) -> int | None:
        now, v = self.clock(), self.read()
        if v is not None:
            self.samples.append((now, v))
        self.samples = [(t, x) for t, x in self.samples if now - t <= self.window_s]
        return int(statistics.median(x for _, x in self.samples)) if self.samples else None

    def pegged(self, n: int = 3, pct: int = 95) -> bool:
        """The last `n` readings all at `pct` or more: a GPU someone keeps fully busy, seen at once rather than when
        it takes over the median (the desktop's spikes stay under 90 %)."""
        last = [x for _, x in self.samples[-n:]]
        return len(last) == n and min(last) >= pct


class HubMeter:
    """The `aihub` measure (see the module's docstring): 100 while another GPU mod works or the device is busy,
    else the other mods' `gpu_busy_pct`. An unreachable hub leaves the device's median as the reading."""

    def __init__(self, hub_url: str | None, me: str = "embed", device: Callable[[], int | None] | None = None,
                 device_pct: float = 30, get: Callable[[str], Any] | None = None):
        self.url, self.me = (hub_url or "").rstrip("/"), me
        self.device = device or DeviceMedian()
        self.device_pct = device_pct
        self.get = get or (lambda url: httpx.get(url, timeout=2).json())
        self.measure = "aihub"
        self.detail: dict[str, Any] = {}

    def __call__(self) -> int | None:
        dev = self.device()
        self.detail = {"device_median_pct": dev, "device_pct": self.device_pct}
        if dev is not None and (dev >= self.device_pct or getattr(self.device, "pegged", lambda: False)()):
            return 100
        if not self.url:
            return 0 if dev is not None else None
        try:
            services = self.get(f"{self.url}/api/services")
            rows = self.get(f"{self.url}/api/memory").get("by_service") or []
        except (httpx.HTTPError, ValueError, AttributeError):
            return 0 if dev is not None else None
        working = [s["id"] for s in services if s.get("id") != self.me and s.get("load") not in (None, "n/a")
                   and s.get("state") in ("ready", "degraded", "starting")
                   and (s.get("busy") or s.get("in_flight") or any(j.get("state") in ("queued", "running") for j in s.get("jobs") or []))]
        vulkan = round(sum(r.get("gpu_busy_pct") or 0 for r in rows if r.get("id") != self.me))
        self.detail.update(mods_working=working, mods_gpu_busy_pct=vulkan)
        return 100 if working else min(100, vulkan)


class GpuIdle:
    def __init__(self, busy_pct: float = 10, idle_s: float = 300, ours: Callable[[], bool] = lambda: False,
                 read: Callable[[], int | None] = read_busy, clock: Callable[[], float] = time.monotonic,
                 grace_s: float = 1.5, sleep: Callable[[float], None] = time.sleep):
        self.busy_pct, self.idle_s, self.ours, self.read, self.clock, self.grace_s = busy_pct, idle_s, ours, read, clock, grace_s
        self._sleep = sleep
        self.quiet_since = clock()                      # a start counts as busy: wait the full period first
        self.last: int | None = None
        self.ours_until = 0.0

    def sample(self) -> None:
        """Once a second (the server's loop)."""
        now = self.clock()
        if self.ours():
            self.ours_until = now + self.grace_s
            return
        if now < self.ours_until:
            return
        self.last = self.read()
        if self.last is not None and self.last >= self.busy_pct:
            self.quiet_since = now

    def busy_now(self, reads: int = 3, gap_s: float = 0.1) -> bool:
        """A fresh look between batches (our batch is done): the highest of a few reads. Busy restarts the wait."""
        vals = []
        for i in range(reads):
            if i:
                self._sleep(gap_s)
            v = self.read()
            if v is not None:
                vals.append(v)
        self.last = max(vals) if vals else None
        busy = bool(vals) and self.last >= self.busy_pct
        if busy:
            self.quiet_since = self.clock()
        return busy

    def idle(self) -> bool:
        return self.clock() - self.quiet_since >= self.idle_s

    def quiet_s(self) -> float:
        return round(self.clock() - self.quiet_since, 1)
