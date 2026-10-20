"""When the GPU is free for background indexing (plan 28.2, decided 2026-10-20): its busy percentage, sampled
every second, has stayed under `busy_pct` for `idle_s`.

Two sources (`EMBED_IDLE_SOURCE`):
- `engine` (the default): the share of time other processes kept the GPU's busiest engine working, from each
  DRM client's `drm-engine-*` counters in `/proc/*/fdinfo`, leaving out the embed mod's own processes. It
  measures work.
- `busy_percent`: `/sys/class/drm/card*/device/gpu_busy_percent`, as first decided. On gfx1151 it sits at
  13–17 % with nothing running and jumps to 80–90 % about every 15 s (measured 2026-10-20, while the engine
  counters showed 3.5 %), so "under 10 % for 5 minutes" never happens there.

Our own encoding makes the GPU busy too, so samples taken while the encoder works (and for `grace_s` after) are
left out: they neither count as quiet nor as busy. Between batches the indexer reads the GPU afresh (`busy_now`);
any other work on the GPU then stops indexing and the quiet period starts again. A machine without the file
(no amdgpu) counts as idle.
"""

from __future__ import annotations

import glob
import os
import re
import time
from collections.abc import Callable
from pathlib import Path

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


ENGINE_RE = re.compile(r"^drm-engine-([\w-]+):\s+(\d+) ns", re.MULTILINE)
CLIENT_RE = re.compile(r"^drm-client-id:\s+(\d+)", re.MULTILINE)


def engine_counters(proc: Path = Path("/proc")) -> dict[str, tuple[set[int], dict[str, int]]]:
    """Each DRM client (an open GPU device, shared between processes after a fork): its pids and its engines'
    busy nanoseconds."""
    out: dict[str, tuple[set[int], dict[str, int]]] = {}
    for d in proc.iterdir():
        if not d.name.isdigit():
            continue
        try:
            fds = list((d / "fdinfo").iterdir())
        except OSError:
            continue
        for f in fds:
            try:
                text = f.read_text()
            except OSError:
                continue
            c = CLIENT_RE.search(text)
            if not c:
                continue
            pids, eng = out.setdefault(c.group(1), (set(), {}))
            pids.add(int(d.name))
            for name, ns in ENGINE_RE.findall(text):
                eng[name] = max(eng.get(name, 0), int(ns))
    return out


class EngineMeter:
    """A `read` for GpuIdle: percent of the time since the last read that other processes kept the busiest
    engine working. The first read only takes a snapshot (None)."""

    def __init__(self, exclude: Callable[[], set[int]] = lambda: {os.getpid()},
                 counters: Callable[[], dict[str, tuple[set[int], dict[str, int]]]] = engine_counters,
                 clock: Callable[[], float] = time.monotonic):
        self.exclude, self.counters, self.clock = exclude, counters, clock
        self.prev: dict[str, dict[str, int]] | None = None
        self.t = 0.0

    def __call__(self) -> int | None:
        snap, now = self.counters(), self.clock()
        ours = self.exclude()
        cur = {cid: eng for cid, (pids, eng) in snap.items() if not pids & ours}
        prev, dt = self.prev, now - self.t
        self.prev, self.t = cur, now
        if prev is None or dt <= 0:
            return None
        per_engine: dict[str, int] = {}
        for cid, eng in cur.items():
            before = prev.get(cid)
            if before is None:                          # a client opened since the last read: count from now
                continue
            for name, ns in eng.items():
                per_engine[name] = per_engine.get(name, 0) + max(0, ns - before.get(name, ns))
        busiest = max(per_engine.values(), default=0)
        return min(100, round(busiest / (dt * 1e9) * 100))


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
