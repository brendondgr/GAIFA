"""The recorder (plan 6.1, architecture §13): what gets written, and when.

- **Every 10 s** (on the 10 s grid): the memory sampler's latest numbers (`mem.*`, `gpu.*`,
  `mem.svc.<id>`), `jobs.running`, and each ready mod's numeric stats as
  `svc.<id>.stat.<slug>` from its latest status. A `"reset": "daily"` counter that drops on a
  new day records one `None` instead, so a chart breaks the line rather than drawing a drop.
  A heartbeat in `kv` notes the last tick.
- **Events:** `service` events open and close `service_states` rows and `load_intervals`;
  `job` events fill `job_history`. On start (and on a bus `resync`) the current state of
  every mod is read directly, since events from before then were not seen.
- **After downtime:** rows still open from the last run are closed at the last heartbeat, so a
  hub that was down shows as a gap. A job that reappears with the same id (its mod kept running)
  is reopened.
- **Hourly:** roll up and prune (`Store.rollup`). Also the low-disk alert (plan 6.4).
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import sqlite3
import time
from datetime import datetime
from typing import TYPE_CHECKING, Any, Callable

from utils.metrics.store import HOUR, RAW_STEP, SeriesInfo, Store
from utils.services.status import ACTIVE_JOBS, slug

if TYPE_CHECKING:
    from utils.db import Database
    from utils.events import Alerts, EventBus
    from utils.memory import MemoryManager
    from utils.services import ServiceManager

log = logging.getLogger("gaifa.metrics")

HEARTBEAT = "metrics.heartbeat"
LOADED = {"loaded", "unloading"}  # models are in memory until the unload finishes
FINAL_JOBS = {"done", "failed", "cancelled"}
DISK_ALERT = "disk-low"
DISK_LOW_BYTES = 50 * 1000**3
DISK_CLEAR_BYTES = 55 * 1000**3

MEM_SERIES = {
    "mem.total": ("Memory total", "total_bytes"),
    "mem.used": ("Memory used", "used_bytes"),
    "mem.available": ("Memory available", "available_bytes"),
    "mem.reserve": ("Memory reserve", "reserve_bytes"),
    "mem.other": ("Other (not mods)", "other_bytes"),
}
STATIC = {
    **{n: SeriesInfo(n, label, "bytes") for n, (label, _) in MEM_SERIES.items()},
    "gpu.gtt_used": SeriesInfo("gpu.gtt_used", "GPU memory (GTT) used", "bytes"),
    "gpu.vram_used": SeriesInfo("gpu.vram_used", "GPU VRAM used", "bytes"),
    "jobs.running": SeriesInfo("jobs.running", "Jobs running", "count"),
    "gpu.waiting": SeriesInfo("gpu.waiting", "Waiting for the GPU", "count"),
}


class Recorder:
    def __init__(self, services: ServiceManager, memory: MemoryManager | None, db: Database, bus: EventBus,
                 alerts: Alerts | None = None, disk_path: Any = None, every: float = RAW_STEP,
                 maintain_every: float = HOUR, clock: Callable[[], float] = time.time) -> None:
        self.mgr, self.memory, self.db, self.bus, self.alerts = services, memory, db, bus, alerts
        self.store = Store(db)
        self.disk_path = disk_path
        self.every, self.maintain_every, self.clock = every, maintain_every, clock
        self._states: dict[str, tuple[str, int]] = {}  # service → (state, open row id)
        self._loads: dict[str, int] = {}  # service → open load_intervals row id
        self._jobs: dict[tuple[str, str], tuple[int, str, str]] = {}  # (service, job id) → (row id, state, label)
        self._reopenable: dict[tuple[str, str], int] = {}  # jobs closed at startup: reopened if seen again
        self._last_stat: dict[str, tuple[float, str]] = {}  # daily counters: (value, local date)
        self._tools: dict[tuple[str, str], int] = {}       # (mod, "calls" | "errors") → finished this tick
        self._tasks: list[asyncio.Task[None]] = []
        self.gpu: Any = None                               # utils.gpu.GpuQueue (plan 31.1): wait and hold times per mod
        self._sub: Any = None
        self.last_tick: int | None = None

    # lifecycle ----------------------------------------------------------------------

    async def start(self) -> None:
        await self.recover()
        self._sub = self.bus.subscribe()
        await self.reconcile()
        try:
            await self.store.rollup(self.clock())
        except Exception:  # noqa: BLE001
            log.exception("metrics rollup")
        self._tasks = [asyncio.create_task(self._tick_loop(), name="gaifa-metrics"),
                       asyncio.create_task(self._event_loop(), name="gaifa-metrics-events"),
                       asyncio.create_task(self._maintain_loop(), name="gaifa-metrics-rollup")]

    async def close(self) -> None:
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        if self._sub:
            self._sub.close()
        # Close what is open now, so the next start sees exactly when the hub stopped.
        try:
            await self._close_all(self.clock())
        except Exception:  # noqa: BLE001: the database may already be closing
            log.exception("metrics close")

    async def recover(self) -> None:
        """Close rows left open by a hub that stopped without closing them, at its last heartbeat."""
        row = await self.db.fetchone("SELECT value FROM kv WHERE key = ?", (HEARTBEAT,))
        hb = float(row["value"]) if row and row["value"] else None

        def run(c: sqlite3.Connection) -> list[tuple[int, str, str]]:
            open_jobs = c.execute("SELECT id, service, job_id FROM job_history WHERE end_ts IS NULL").fetchall()
            for table, col in (("service_states", "to_ts"), ("load_intervals", "to_ts")):
                # No heartbeat (never ticked): end them where they began.
                c.execute(f"UPDATE {table} SET {col} = MAX(from_ts, COALESCE(?, from_ts)) WHERE {col} IS NULL", (hb,))
            c.execute("UPDATE job_history SET end_ts = MAX(start_ts, COALESCE(?, start_ts)), state = 'cancelled' "
                      "WHERE end_ts IS NULL", (hb,))
            return [(r[0], r[1], r[2]) for r in open_jobs]

        for rid, service, job_id in await self.db.write(run):
            self._reopenable[(service, job_id)] = rid

    # ticks --------------------------------------------------------------------------

    async def _tick_loop(self) -> None:
        last = 0.0
        while True:
            now = self.clock()
            due = max((now // self.every + 1) * self.every, last + self.every)  # never the same boundary twice
            last = due
            await asyncio.sleep(max(0.0, due - now))
            try:
                # Stamp the tick with the boundary it waited for: a sleep that wakes a hair early
                # would otherwise land in the previous 10 s bucket and leave this one empty.
                await self.tick(ts=max(due, self.clock()) if self.every >= RAW_STEP else None)
            except Exception:  # noqa: BLE001: keep recording
                log.exception("metrics tick")

    async def tick(self, ts: int | None = None) -> list[tuple[SeriesInfo, float | None]]:
        ts = int((ts if ts is not None else self.clock()) // RAW_STEP * RAW_STEP)  # on the 10 s grid
        samples = self.samples(ts)
        hb = ts

        def extra(c: sqlite3.Connection) -> None:
            c.execute("INSERT INTO kv (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                      (HEARTBEAT, str(hb)))

        await self.store.record(ts, samples, extra)
        self.last_tick = ts
        self.check_disk()
        return samples

    def samples(self, ts: int) -> list[tuple[SeriesInfo, float | None]]:
        out: list[tuple[SeriesInfo, float | None]] = []
        mem = self.memory.snapshot if self.memory else None
        if mem and mem.get("total_bytes"):
            for name, (_, key) in MEM_SERIES.items():
                out.append((STATIC[name], float(mem[key])))
            gpu = mem.get("gpu")
            if gpu:
                out.append((STATIC["gpu.gtt_used"], float(gpu.get("gtt_used_bytes") or 0)))
                if gpu.get("vram_total_bytes"):
                    out.append((STATIC["gpu.vram_used"], float(gpu.get("vram_used_bytes") or 0)))
            for pool in mem.get("pools", [])[1:]:       # each dedicated GPU's VRAM (plan 36.4)
                n = pool["id"].split(":", 1)[1]
                out.append((SeriesInfo(f"gpu.{n}.mem_used", f"{pool['name']} VRAM used", "bytes"), float(pool["used_bytes"])))
            for row in mem.get("by_service", []):
                out.append((SeriesInfo(f"mem.svc.{row['id']}", self._name(row["id"]), "bytes", service=row["id"]), float(row["used_bytes"])))
        running = 0
        day = datetime.fromtimestamp(ts).date().isoformat()
        for svc in self.mgr.list():
            running += sum(1 for j in svc.jobs if j["state"] == "running")
            if svc.state not in ("ready", "degraded"):
                continue
            seen: set[str] = set()
            for st in svc.stats:
                v = st.get("value")
                if not isinstance(v, (int, float)) or isinstance(v, bool):
                    continue
                name = f"svc.{svc.id}.stat.{slug(st['label'])}"
                if name in seen:
                    continue
                seen.add(name)
                reset = st.get("reset")
                info = SeriesInfo(name, st["label"], st.get("unit") or "count", service=svc.id, reset=reset)
                value: float | None = float(v)
                if reset == "daily":
                    last = self._last_stat.get(name)
                    self._last_stat[name] = (float(v), day)
                    if last and last[1] != day and float(v) < last[0]:
                        value = None  # the counter reset at midnight: break the line instead of a drop
                out.append((info, value))
        out.append((STATIC["jobs.running"], float(running)))
        out += self.gpu_samples()
        tools, self._tools = self._tools, {}
        for (mod, what), n in sorted(tools.items()):       # finished tool calls in this tick, per mod (plan 21.1)
            out.append((SeriesInfo(f"tools.{what}.{mod}", f"{self._name(mod) if mod != 'hub' else 'GAIFA'} tool {what}", "count",
                                   service=None if mod == "hub" else mod), float(n)))
        return out

    def gpu_samples(self) -> list[tuple[SeriesInfo, float | None]]:
        """`gpu.waiting` now, and per mod the mean wait (`gpu.wait.<id>`) and hold (`gpu.hold.<id>`) of the leases
        granted or finished in this tick, in seconds (plan 31.1)."""
        if self.gpu is None:
            return []
        out: list[tuple[SeriesInfo, float | None]] = [(STATIC["gpu.waiting"], float(len(self.gpu.waiting())))]
        sums: dict[tuple[str, str], list[float]] = {}
        for sid, what, secs in self.gpu.drain_stats():
            sums.setdefault((sid, what), []).append(secs)
        for (sid, what), vals in sorted(sums.items()):
            label = f"{self._name(sid)}: {'wait for' if what == 'wait' else 'time on'} the GPU"
            out.append((SeriesInfo(f"gpu.{what}.{sid}", label, "seconds", service=sid), round(sum(vals) / len(vals), 1)))
        return out

    def tool_event(self, call: dict[str, Any]) -> None:
        """A finished tool call (not a dry run) counts toward `tools.calls.<mod>` / `tools.errors.<mod>`."""
        if call.get("status") not in ("done", "error", "cancelled") or (call.get("origin") or {}).get("dry_run"):
            return
        mod = str(call.get("tool") or "").split("_", 1)[0] or "hub"
        svc = next((s for s in self.mgr.list() if (call.get("tool") or "").startswith(s.id.replace("-", "_") + "_")), None)
        mod = svc.id if svc else mod
        self._tools[(mod, "calls")] = self._tools.get((mod, "calls"), 0) + 1
        if call.get("status") == "error":
            self._tools[(mod, "errors")] = self._tools.get((mod, "errors"), 0) + 1

    def _name(self, sid: str) -> str:
        svc = self.mgr.services.get(sid)
        return svc.mod.name if svc else sid

    def check_disk(self) -> None:
        if not self.alerts or self.disk_path is None:
            return
        try:
            free = shutil.disk_usage(self.disk_path).free
        except OSError:
            return
        if free < DISK_LOW_BYTES:
            self.alerts.set(DISK_ALERT, "error" if free < DISK_LOW_BYTES / 5 else "warn",
                            f"Disk space is low: {free / 1000**3:.1f} GB free",
                            action={"label": "Outputs", "route": "#/outputs"})
        elif free >= DISK_CLEAR_BYTES:
            self.alerts.clear(DISK_ALERT)

    # events -------------------------------------------------------------------------

    async def _event_loop(self) -> None:
        async for ev in self._sub:
            try:
                await self.on_event(ev)
            except Exception:  # noqa: BLE001
                log.exception("metrics event %s", ev.get("type"))

    async def on_event(self, ev: dict[str, Any]) -> None:
        kind = ev.get("type")
        if kind == "service":
            s = ev["service"]
            await self.service(s["id"], s["state"], s["load"])
        elif kind == "job":
            await self.job(ev["job"])
        elif kind == "resync":
            await self.reconcile()
        elif kind == "tool_call":
            self.tool_event(ev.get("call") or {})

    async def reconcile(self) -> None:
        """Bring the open rows in line with every mod's current state (start, resync, removed mods)."""
        now = self.clock()
        # Read everything before the first await: events published after this point are newer
        # than the snapshot, so applying them afterwards keeps the order right.
        current = {svc.id: (svc.state, svc.load, [{**j, "service": svc.id} for j in svc.jobs]) for svc in self.mgr.list()}
        for sid in [s for s in self._states if s not in current]:
            await self.service(sid, None, None, now)
        for sid, (state, load, jobs) in current.items():
            await self.service(sid, state, load, now)
            for j in jobs:
                await self.job(j, now)

    async def service(self, sid: str, state: str | None, load: str | None, now: float | None = None) -> None:
        now = self.clock() if now is None else now
        cur = self._states.get(sid)
        if cur is None or cur[0] != state:
            def run(c: sqlite3.Connection) -> int | None:
                if cur:
                    c.execute("UPDATE service_states SET to_ts = ? WHERE id = ?", (now, cur[1]))
                if state is None:
                    return None
                return c.execute("INSERT INTO service_states (service, state, from_ts) VALUES (?, ?, ?)", (sid, state, now)).lastrowid

            rid = await self.db.write(run)
            if rid is None:
                self._states.pop(sid, None)
            else:
                self._states[sid] = (state, rid)
        loaded = load in LOADED
        open_id = self._loads.get(sid)
        if loaded and open_id is None:
            self._loads[sid] = await self.db.execute("INSERT INTO load_intervals (service, from_ts) VALUES (?, ?)", (sid, now))
        elif not loaded and open_id is not None:
            await self.db.execute("UPDATE load_intervals SET to_ts = ? WHERE id = ?", (now, open_id))
            del self._loads[sid]

    async def job(self, job: dict[str, Any], now: float | None = None) -> None:
        now = self.clock() if now is None else now
        key = (job["service"], job["id"])
        state, label, route = job["state"], job.get("label") or job["id"], job.get("route")
        cur = self._jobs.get(key)
        if cur is None and state in ACTIVE_JOBS and key in self._reopenable:
            rid = self._reopenable.pop(key)
            await self.db.execute("UPDATE job_history SET end_ts = NULL, state = ?, label = ? WHERE id = ?", (state, label, rid))
            cur = self._jobs[key] = (rid, state, label)
        if cur is None:
            end = now if state in FINAL_JOBS else None
            rid = await self.db.execute(
                "INSERT INTO job_history (service, job_id, label, state, start_ts, end_ts, route) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (job["service"], job["id"], label, state, now, end, route))
            if end is None:
                self._jobs[key] = (rid, state, label)
            return
        rid, old_state, old_label = cur
        if state in FINAL_JOBS:
            await self.db.execute("UPDATE job_history SET state = ?, label = ?, end_ts = ? WHERE id = ?", (state, label, now, rid))
            del self._jobs[key]
        elif (state, label) != (old_state, old_label):
            await self.db.execute("UPDATE job_history SET state = ?, label = ? WHERE id = ?", (state, label, rid))
            self._jobs[key] = (rid, state, label)

    async def _close_all(self, now: float) -> None:
        def run(c: sqlite3.Connection) -> None:
            c.executemany("UPDATE service_states SET to_ts = ? WHERE id = ?", [(now, rid) for _, rid in self._states.values()])
            c.executemany("UPDATE load_intervals SET to_ts = ? WHERE id = ?", [(now, rid) for rid in self._loads.values()])
            c.execute("INSERT INTO kv (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                      (HEARTBEAT, str(now)))
            # Jobs stay open: the mod may still be running them. The next start closes them at
            # this heartbeat, and reopens any that reappear.

        await self.db.write(run)
        self._states.clear()
        self._loads.clear()

    # maintenance ----------------------------------------------------------------------

    async def _maintain_loop(self) -> None:
        while True:
            await asyncio.sleep(self.maintain_every)
            try:
                await self.store.rollup(self.clock())
            except Exception:  # noqa: BLE001
                log.exception("metrics rollup")
            try:
                from utils.tools.records import prune_dry_runs
                await prune_dry_runs(self.db, self.clock())
            except Exception:  # noqa: BLE001
                log.exception("pruning dry-run tool records")
