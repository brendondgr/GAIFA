"""The memory manager (architecture §7, plan 5.2–5.4): samples memory every 2 s, plans
make-room, and frees memory one mod at a time.

- **Sampling:** each running mod's footprint (`source.py`), the brief's `Memory` shape,
  a `memory` event when anything moves by more than 1% of total (or a load state
  changes, or every 10 s), learned peaks in `service_peaks`, and a `memory-high` alert
  above 92% (cleared below 90%).
- **Room:** `ensure_room()` is the one way in for loads, proxied triggers and mods'
  `acquire` calls. Under one lock it plans, unloads if allowed (`make_room`, or
  `[memory] auto_make_room`), and then **reserves** what the load needs, so a second load
  planned meanwhile doesn't count the same memory. A reservation shrinks as the mod's
  measured use grows, and ends when the load does (or after its time to live).
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from utils import proc
from utils.memory.planner import GB, Candidate, describe, extend_plan, fmt_gb, make_plan, why_not
from utils.memory.pools import Pool
from utils.memory.source import ProcSource, Source
from utils.services.model import ServiceError

if TYPE_CHECKING:
    from utils.db import Database
    from utils.events import ActivityLog, Alerts, EventBus
    from utils.services import ServiceManager
    from utils.services.model import Service

log = logging.getLogger("aihub.memory")

EVERY_S = 2.0
PUBLISH_EVERY_S = 10.0
MOVE_FRACTION = 0.01
ALERT = "memory-high"
ALERT_ABOVE, ALERT_CLEAR = 0.92, 0.90
WAIT_S = 30.0  # for memory to drop after an unload
DROP_FRACTION = 0.7  # …by at least this share of what the plan expected
POLL_S = 0.25
LOAD_TTL_S = 30 * 60.0  # a load that never finishes doesn't hold memory forever
ACQUIRE_TTL_S = 120.0
TRIGGER_TTL_S = 300.0
VRAM_KEY = "@gpu"   # service_peaks rows `<id>@gpu`: a mod's VRAM peak on a dedicated GPU (mod ids have no @)


@dataclass
class Reservation:
    bytes: int
    base_used: int
    expires: float
    grown: int = 0  # the most the mod's measured use has grown since: a reservation only shrinks
    vram: int = 0               # plan 36.2: VRAM reserved on a dedicated GPU's pool
    vram_pool: str | None = None
    vram_base: int = 0
    vram_grown: int = 0


def needs_room(plan: dict[str, Any], name: str) -> ServiceError:
    return ServiceError(409, "needs_room", describe(plan, name), {"plan": plan})


class MemoryManager:
    def __init__(self, services: ServiceManager, db: Database | None, bus: EventBus, alerts: Alerts | None = None,
                 activity: ActivityLog | None = None, source: Source | None = None, every: float = EVERY_S,
                 wait_s: float = WAIT_S, poll_s: float = POLL_S) -> None:
        self.mgr, self.db, self.bus, self.alerts, self.activity = services, db, bus, alerts, activity
        self.source: Source = source or ProcSource()
        self.every, self.wait_s, self.poll_s = every, wait_s, poll_s
        self.lock = asyncio.Lock()
        self.sys: dict[str, int] = {"total_bytes": 0, "used_bytes": 0, "available_bytes": 0}
        self.gpu: dict[str, Any] | None = None
        self.used: dict[str, int] = {}
        self.pools: list[Pool] = []                      # dedicated GPUs' pools (plan 36.1); none: one pool
        self.vram: dict[str, dict[str, int]] = {}        # mod → GPU pool → VRAM bytes
        self.gpu_busy: dict[str, float] = {}           # each mod's GPU busy % since the last sample (plan 28.2)
        self._engines: tuple[dict[str, dict[str, int]], float] | None = None
        self.peaks: dict[str, int] = {}
        self.peak_ts: dict[str, float] = {}              # when each peak was measured (time.time())
        self.reservations: dict[str, Reservation] = {}
        self.snapshot: dict[str, Any] | None = None
        self._last_pub: tuple[float, dict[str, Any]] | None = None
        self._task: asyncio.Task[None] | None = None

    @property
    def cfg(self) -> Any:
        return self.mgr.config.memory

    # lifecycle -----------------------------------------------------------------

    async def start(self) -> None:
        if self.db:
            rows = await self.db.fetchall("SELECT service, peak_bytes, updated_ts FROM service_peaks")
            self.peaks = {r["service"]: r["peak_bytes"] for r in rows}
            self.peak_ts = {r["service"]: r["updated_ts"] or 0.0 for r in rows}
        await self.sample()
        self._task = asyncio.create_task(self._loop(), name="aihub-memory")

    async def close(self) -> None:
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(self.every)
            try:
                await self.sample()
            except Exception:  # noqa: BLE001: keep sampling
                log.exception("memory sample")

    # sampling --------------------------------------------------------------------

    async def sample(self, publish: bool = True) -> dict[str, Any]:
        pids = await self.source.collect(self.mgr)
        self.sys, self.gpu, self.used = await asyncio.to_thread(self.source.read, pids)
        read_pools = getattr(self.source, "pools", None)
        if read_pools is not None:
            self.pools, self.vram = await asyncio.to_thread(read_pools, pids)
        await self._sample_engines(pids)
        await self._learn_peaks()
        mem = self.view()
        self.snapshot = mem
        if publish and self._moved(mem):
            self.bus.publish({"type": "memory", "memory": mem})
            self._last_pub = (time.monotonic(), mem)
        self._alert(mem)
        return mem

    async def _sample_engines(self, pids: dict[str, list[int]]) -> None:
        """Each mod's GPU busy percentage since the last sample (`gpu_busy_pct`), when the source reads engines."""
        read = getattr(self.source, "engines", None)
        if read is None:
            return
        now, eng = time.monotonic(), await asyncio.to_thread(read, pids)
        prev, t = self._engines or ({}, now)
        self.gpu_busy = {sid: proc.busy_pct(prev[sid], e, now - t) for sid, e in eng.items() if sid in prev and now > t}
        self._engines = (eng, now)

    def estimate(self, svc: Service) -> int | None:
        gb = svc.memory_estimate_gb if svc.memory_estimate_gb is not None else (svc.m.memory.estimate_gb if svc.m and svc.m.memory else None)
        return round(gb * GB) if gb is not None else None

    def fresh_peak(self, sid: str) -> int:
        """The learned peak, while it is younger than `[memory] peak_days`: an old one (a workflow or engine
        since retired) would otherwise ask for its worst moment forever."""
        if time.time() - self.peak_ts.get(sid, time.time()) > self.cfg.peak_days * 86400:
            return 0
        return self.peaks.get(sid, 0)

    def vram_estimate(self, svc: Service) -> int | None:
        gb = svc.m.memory.vram_gb if svc.m and svc.m.memory else None
        return round(gb * GB) if gb is not None else None

    def needs(self, svc: Service) -> int:
        est = self.estimate(svc) or 0
        if not self.pools:                       # one pool: its VRAM is the system's memory too
            est += self.vram_estimate(svc) or 0
        return max(est, self.fresh_peak(svc.id))

    def needs_vram(self, svc: Service) -> int:
        return max(self.vram_estimate(svc) or 0, self.fresh_peak(svc.id + VRAM_KEY)) if self.pools else 0

    def vram_used(self, sid: str, pool: str) -> int:
        return self.vram.get(sid, {}).get(pool, 0)

    def gpu_pool(self, svc: Service, device: int | None = None) -> str | None:
        """The dedicated GPU pool a mod's VRAM goes to: the device asked for, else where it already
        holds VRAM, else the one with the most free (plan 36.3 adds `[services.<id>] gpu`)."""
        if not self.pools:
            return None
        ids = [p.id for p in self.pools]
        pinned = getattr(svc.eff, "gpu", None) if device is None else device
        if pinned is not None and f"gpu:{pinned}" in ids:
            return f"gpu:{pinned}"
        held = self.vram.get(svc.id)
        if held:
            return max(held, key=lambda k: held[k])
        return max(self.pools, key=lambda p: p.available_bytes).id

    def view(self) -> dict[str, Any]:
        """The brief's `Memory`."""
        rows = []
        for svc in self.mgr.list():
            used = self.used.get(svc.id, 0)
            if not (svc.has_memory or used):
                continue
            row = {"id": svc.id, "used_bytes": used, "estimate_bytes": self.estimate(svc), "load": svc.load,
                   "idle_s": svc.idle_s, "auto_unload": svc.eff.auto_unload, "priority": svc.eff.priority}
            if svc.id in self.gpu_busy:
                row["gpu_busy_pct"] = self.gpu_busy[svc.id]
            rows.append(row)
            if self.pools:
                row["vram_bytes"] = sum(self.vram.get(svc.id, {}).values())
        system = {"id": "system", "name": "System memory", "total_bytes": self.sys["total_bytes"], "used_bytes": self.sys["used_bytes"],
                  "available_bytes": self.sys["available_bytes"]}
        return {
            "total_bytes": self.sys["total_bytes"], "used_bytes": self.sys["used_bytes"],
            "available_bytes": self.sys["available_bytes"], "reserve_bytes": round(self.cfg.reserve_gb * GB),
            "gpu": self.gpu, "by_service": rows,
            "other_bytes": max(0, self.sys["used_bytes"] - sum(self.used.values())),
            "pools": [system] + [p.dump() for p in self.pools],
        }

    def _moved(self, mem: dict[str, Any]) -> bool:
        if self._last_pub is None:
            return True
        when, last = self._last_pub
        if time.monotonic() - when >= PUBLISH_EVERY_S or mem["reserve_bytes"] != last["reserve_bytes"]:
            return True
        step = MOVE_FRACTION * max(1, mem["total_bytes"])
        if abs(mem["used_bytes"] - last["used_bytes"]) > step:
            return True
        for p, q in zip(mem["pools"][1:], last.get("pools", [])[1:]):
            if p["id"] != q["id"] or abs(p["used_bytes"] - q["used_bytes"]) > MOVE_FRACTION * max(1, p["total_bytes"]):
                return True
        if len(mem["pools"]) != len(last.get("pools", [])):
            return True
        before = {r["id"]: r for r in last["by_service"]}
        for r in mem["by_service"]:
            b = before.get(r["id"])
            if b is None or b["load"] != r["load"] or abs(b["used_bytes"] - r["used_bytes"]) > step:
                return True
        return len(before) != len(mem["by_service"])

    async def _learn_peaks(self) -> None:
        self.reserved()  # note each reservation's growth while the numbers are fresh
        await self._peaks()

    async def _peaks(self) -> None:
        """A loaded mod's highest measured use, kept in `service_peaks` (written when it grows by 1%+)."""
        for svc in self.mgr.list():
            if svc.load != "loaded":
                continue
            # System memory under the mod's id; its VRAM on a dedicated GPU under `<id>@gpu` (plan 36.2).
            for key, used in ((svc.id, self.used.get(svc.id, 0)), (svc.id + VRAM_KEY, sum(self.vram.get(svc.id, {}).values()))):
                old = self.fresh_peak(key)            # a stale peak is replaced by today's, even a smaller one
                if used <= old * (1 + MOVE_FRACTION):
                    continue
                self.peaks[key] = used
                self.peak_ts[key] = time.time()
                if self.db:
                    await self.db.execute(
                        "INSERT INTO service_peaks (service, peak_bytes, updated_ts) VALUES (?, ?, ?) "
                        "ON CONFLICT(service) DO UPDATE SET peak_bytes = excluded.peak_bytes, updated_ts = excluded.updated_ts",
                        (key, used, time.time()),
                    )

    def _alert(self, mem: dict[str, Any]) -> None:
        if not self.alerts or not mem["total_bytes"]:
            return
        share = mem["used_bytes"] / mem["total_bytes"]
        if share > ALERT_ABOVE:
            self.alerts.set(ALERT, "warn", f"Memory is {share:.0%} full ({fmt_gb(mem['used_bytes'])} of {fmt_gb(mem['total_bytes'])})",
                            action={"label": "Open", "route": "#/overview"})
        elif share < ALERT_CLEAR:
            self.alerts.clear(ALERT)

    # planning ----------------------------------------------------------------------

    def candidates(self) -> list[Candidate]:
        out = []
        for svc in self.mgr.list():
            mem = svc.m.memory if svc.m else None
            out.append(Candidate(
                id=svc.id, name=svc.mod.name, load=svc.load, up=svc.up, busy=svc.busy, in_flight=svc.in_flight,
                auto_unload=svc.eff.auto_unload, unloadable=bool(mem and mem.unload), priority=svc.eff.priority,
                idle_s=svc.idle_s, used_bytes=self.used.get(svc.id, 0), estimate_bytes=self.estimate(svc),
            ))
        return out

    def _remaining(self, sid: str, r: Reservation) -> int:
        r.grown = max(r.grown, self.used.get(sid, 0) - r.base_used)
        return max(0, r.bytes - r.grown)

    def reserved(self, but: str | None = None) -> int:
        now = time.monotonic()
        for sid in [s for s, r in self.reservations.items() if r.expires <= now]:
            del self.reservations[sid]
        return sum(self._remaining(sid, r) for sid, r in self.reservations.items() if sid != but)

    def reserved_vram(self, pool: str, but: str | None = None) -> int:
        self.reserved()          # drop the expired ones
        out = 0
        for sid, r in self.reservations.items():
            if sid != but and r.vram_pool == pool:
                r.vram_grown = max(r.vram_grown, self.vram_used(sid, pool) - r.vram_base)
                out += max(0, r.vram - r.vram_grown)
        return out

    def plan(self, service_id: str, needs_bytes: int | None = None, available: int | None = None,
             vram_bytes: int | None = None, device: int | None = None, pool_available: int | None = None) -> dict[str, Any]:
        svc = self.mgr.get(service_id)
        needs = needs_bytes if needs_bytes is not None else self.needs(svc)
        avail = (self.sys["available_bytes"] if available is None else available) - round(self.cfg.reserve_gb * GB) - self.reserved(but=service_id)
        cands, never = self.candidates(), set(self.cfg.never_unload)
        plan = make_plan(service_id, needs, avail, cands, never)
        plan["pool"] = "system"
        plan["pools"] = [{"pool": "system", "name": "system memory", "needs_bytes": plan["needs_bytes"], "available_bytes": plan["available_bytes"], "enough": plan["enough"]}]
        gp = self.gpu_pool(svc, device)
        vneeds = (vram_bytes if vram_bytes is not None else self.needs_vram(svc)) if gp else 0
        if gp and vneeds:
            pool = next(p for p in self.pools if p.id == gp)
            pav = (pool.available_bytes if pool_available is None else pool_available) - self.reserved_vram(gp, but=service_id)
            frees = {c.id: self.vram_used(c.id, gp) or ((self.vram_estimate(self.mgr.get(c.id)) or 0) if c.load == "loaded" else 0) for c in cands}
            extend_plan(plan, gp, pool.name, vneeds, pav, cands, never, frees)
        return plan

    async def fresh_plan(self, service_id: str, needs_bytes: int | None = None, vram_bytes: int | None = None, device: int | None = None) -> dict[str, Any]:
        svc = self.mgr.get(service_id)
        gp = self.gpu_pool(svc, device)
        pav = await asyncio.to_thread(self.source.pool_available, gp) if gp and hasattr(self.source, "pool_available") else None
        return self.plan(service_id, needs_bytes, await asyncio.to_thread(self.source.available), vram_bytes, device, pav)

    async def precheck(self, service_id: str, make_room: bool = False, needs_bytes: int | None = None) -> dict[str, Any]:
        """Raise `needs_room` now (for a 409) if a load can't go ahead as asked."""
        plan = await self.fresh_plan(service_id, needs_bytes)
        if plan["unload"] or not plan["enough"]:
            if not plan["enough"] or not (make_room or self.cfg.auto_make_room):
                raise needs_room(plan, self.mgr.get(service_id).mod.name)
        return plan

    # making room ------------------------------------------------------------------------

    async def ensure_room(self, service_id: str, needs_bytes: int | None = None, *, make_room: bool = False,
                          ttl: float = LOAD_TTL_S, vram_bytes: int | None = None, device: int | None = None) -> tuple[dict[str, Any], list[str]]:
        """Plan, unload what the plan says (if allowed), and reserve the memory. Returns
        (plan, freed ids); raises `needs_room` when there isn't room and it can't be made."""
        svc = self.mgr.get(service_id)
        allowed = make_room or self.cfg.auto_make_room
        async with self.lock:
            plan = await self.fresh_plan(service_id, needs_bytes, vram_bytes, device)
            freed: list[str] = []
            if plan["unload"] or not plan["enough"]:
                if not plan["enough"] or not allowed:
                    raise needs_room(plan, svc.mod.name)
                freed = await self._make_room(plan, svc)
                await self.sample()
                plan = await self.fresh_plan(service_id, needs_bytes, vram_bytes, device)
                if not plan["enough"]:
                    raise needs_room(plan, svc.mod.name)
                if plan["unload"]:  # memory didn't drop as much as measured use promised
                    raise needs_room(plan, svc.mod.name)
            r = Reservation(plan["needs_bytes"], self.used.get(service_id, 0), time.monotonic() + ttl)
            gpu = next((p for p in plan["pools"] if p["pool"] != "system"), None)
            if gpu:
                r.vram, r.vram_pool, r.vram_base = gpu["needs_bytes"], gpu["pool"], self.vram_used(service_id, gpu["pool"])
            self.reservations[service_id] = r
        return plan, freed

    def unloaded(self, service_id: str) -> None:
        """An unloaded mod holds nothing, reserved or not."""
        self.reservations.pop(service_id, None)

    def release(self, service_id: str) -> None:
        """The load finished: keep the reservation one more sample or two, until its use is measured."""
        r = self.reservations.get(service_id)
        if r:
            r.expires = min(r.expires, time.monotonic() + 2 * self.every)

    async def _make_room(self, plan: dict[str, Any], target: Service) -> list[str]:
        from utils.services import loading

        never = set(self.cfg.never_unload)
        freed: list[str] = []
        by_id = {c.id: c for c in self.candidates()}
        for u in plan["unload"]:
            c = by_id.get(u["id"])
            if c is None or why_not(c, target.id, never) is not None:
                continue  # it changed meanwhile (became busy, was unloaded…)
            other = self.mgr.get(u["id"])
            pool = u.get("pool", "system")
            if pool == "system":
                read = self.source.available
            else:                           # a GPU's pool: wait on its free VRAM, when it can be read
                pool_read = getattr(self.source, "pool_available", None)
                read = (lambda p=pool: (pool_read(p) if pool_read else None) or 0) if pool_read else None
            before = await asyncio.to_thread(read) if read else 0
            if not await loading.unload_now(self.mgr, other, note=f" to make room for {target.mod.name}"):
                continue
            freed.append(other.id)
            if read is None:
                continue
            goal = before + DROP_FRACTION * u["frees_bytes"]
            deadline = time.monotonic() + self.wait_s
            while await asyncio.to_thread(read) < goal:
                if time.monotonic() > deadline:
                    if self.activity:
                        await self.activity.add(f"{other.mod.name} unloaded, but memory didn't drop by the expected {fmt_gb(u['frees_bytes'])} within {self.wait_s:.0f}s",
                                                service=other.id, level="warn")
                    break
                await asyncio.sleep(self.poll_s)
        return freed
