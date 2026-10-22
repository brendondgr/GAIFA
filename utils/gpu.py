"""The GPU queue (plan 31.1, architecture §7 "GPU queue"): one GPU slot that mods take around their GPU
work, so only one group's work runs at a time.

- **Leases.** A mod asks for the slot (`acquire`) with its `service`, a `group` (default: the mod id), a
  class and a label. The lease is granted at once, or waits in the queue; the caller repeats `acquire`
  with the lease id to keep its place. A held lease is renewed every 10 s and released when the work
  ends.
- **Order.** `interactive` leases go before `job` leases, and `background` leases start only when nothing
  else waits. FIFO within a class. Nothing is pre-empted.
- **Groups share.** While a group holds the slot, more leases of that group join it (an LLM engine
  batches its requests), unless another group's lease of the same or a higher class is waiting: then they
  queue behind it, so a stream of requests can't starve the others.
- **Nested work.** A lease with `parent` (a held lease, passed down in `X-AIHub-GPU-Lease`) is granted at
  once, under its parent: gen3d's job runs comfy's prompt without queueing behind itself.
- **Expiry.** A held lease not renewed for `[gpu] lease_ttl_s` is dropped with the `gpu_lease_expired`
  alert, so a mod that died frees the slot. A waiting lease nobody asks about any more is dropped quietly.
- **Hub restarts.** The queue starts empty; a renewal of a lease the hub doesn't know re-registers it:
  held if the slot is free or held by its group, else waiting.
- **`[gpu] queue = false`:** every lease is granted at once (memory-only admission, as before Phase 31);
  leases are still listed.
- **One slot per GPU (plan 36.3).** A lease is for a `device` (the hardware index; default 0); each
  device has its own slot, holder group and queue, so two cards run two jobs at once. Nested work runs
  on its parent's device. With one GPU this is the queue above, unchanged.
"""

from __future__ import annotations

import asyncio
import itertools
import logging
import secrets
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from utils.config import GpuCfg
    from utils.events import ActivityLog, Alerts, EventBus

log = logging.getLogger("aihub.gpu")

CLASSES = ("interactive", "job", "background")
RANK = {c: i for i, c in enumerate(CLASSES)}
ALERT = "gpu_lease_expired"
HEADER = "X-AIHub-GPU-Lease"
SWEEP_S = 2.0
HISTORY = 20
HOLDS_KEPT = 10          # per service, for the ETA of leases that don't give est_s
WAIT_MAX_S = 60.0
ROOM_PENDING_S = 3600.0   # a deferred trigger's room (on_grant) is dropped if the mod hasn't taken the slot by then


class GpuError(Exception):
    def __init__(self, status: int, code: str, detail: str) -> None:
        super().__init__(detail)
        self.status, self.code, self.detail = status, code, detail


@dataclass
class Lease:
    id: str
    service: str
    group: str
    cls: str
    label: str
    est_s: float | None = None
    thread: str | None = None
    call_id: str | None = None
    parent: str | None = None
    device: int = 0
    seq: int = 0
    created_ts: float = field(default_factory=time.time)
    granted_ts: float | None = None
    renewed_ts: float = field(default_factory=time.time)
    ended_ts: float | None = None
    state: str = "waiting"          # waiting | held | released | expired | cancelled
    touched: float = 0.0            # monotonic: the last acquire, renew or poll
    polling: int = 0                # acquire calls waiting on it right now
    granted: asyncio.Event = field(default_factory=asyncio.Event)

    def view(self) -> dict[str, Any]:
        d: dict[str, Any] = {"id": self.id, "service": self.service, "group": self.group, "class": self.cls,
                             "label": self.label, "state": self.state, "created_ts": self.created_ts,
                             "renewed_ts": self.renewed_ts}
        for k in ("est_s", "thread", "call_id", "parent", "granted_ts", "ended_ts"):
            if getattr(self, k) is not None:
                d[k] = getattr(self, k)
        if self.device:
            d["device"] = self.device
        return d


def new_id() -> str:
    return "gl_" + secrets.token_hex(6)


class GpuQueue:
    def __init__(self, bus: EventBus, alerts: Alerts | None = None, activity: ActivityLog | None = None,
                 cfg: Callable[[], GpuCfg] | None = None, name_of: Callable[[str], str] = lambda s: s,
                 sweep_s: float = SWEEP_S, clock: Callable[[], float] = time.monotonic) -> None:
        from utils.config import GpuCfg

        self.bus, self.alerts, self.activity = bus, alerts, activity
        self.cfg: Callable[[], GpuCfg] = cfg or GpuCfg
        self.name_of, self.sweep_s, self.clock = name_of, sweep_s, clock
        self.leases: dict[str, Lease] = {}       # held and waiting
        self.groups: dict[int, str] = {}           # device → the group holding its slot
        self.history: deque[dict[str, Any]] = deque(maxlen=HISTORY)
        self.holds: dict[str, deque[float]] = {}
        self.stats: list[tuple[str, str, float]] = []   # (service, "wait" | "hold", seconds), drained by metrics
        self._seq = itertools.count(1)
        self._alerted: str | None = None             # the mod named in the expiry alert
        self._tasks: list[asyncio.Task[None]] = []
        self._sub: Any = None
        self._on_grant: dict[str, tuple[float, Callable[[], Any]]] = {}   # service → (until, make its room)

    # lifecycle ---------------------------------------------------------------------

    async def start(self) -> None:
        self._sub = self.bus.subscribe()
        self._tasks = [asyncio.create_task(self._loop(), name="aihub-gpu"),
                       asyncio.create_task(self._follow(), name="aihub-gpu-services")]

    async def close(self) -> None:
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        if self._sub:
            self._sub.close()

    async def _follow(self) -> None:
        """A mod that stops or fails gives its leases back at once (expiry would take a minute)."""
        async for ev in self._sub:
            if ev.get("type") == "service":
                s = ev.get("service") or {}
                if s.get("state") in ("stopped", "failed"):
                    self.service_down(s.get("id", ""), crashed=s.get("state") == "failed")
            elif ev.get("type") == "closed":
                return

    def service_down(self, service: str, crashed: bool = False) -> None:
        for lease in [x for x in self.leases.values() if x.service == service]:
            if crashed and lease.state == "held" and self.alerts:
                self.alerts.set(ALERT, "warn", f"{self.name_of(service)} stopped while it held the GPU ({lease.label}); "
                                "the slot was freed", service=service, action={"label": "Open", "route": f"#/s/{service}"})
                self._alerted = service
            self._end(lease, "expired" if lease.state == "held" else "cancelled")

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(self.sweep_s)
            try:
                self.sweep()
            except Exception:  # noqa: BLE001: keep sweeping
                log.exception("gpu sweep")

    @property
    def enabled(self) -> bool:
        return bool(self.cfg().queue)

    @property
    def ttl(self) -> float:
        return float(self.cfg().lease_ttl_s)

    # reading ---------------------------------------------------------------------------

    @property
    def group(self) -> str | None:
        """The group holding the first GPU's slot (the only slot on a one-GPU machine)."""
        return self.groups.get(0)

    def held(self, device: int | None = None) -> list[Lease]:
        return sorted((x for x in self.leases.values() if x.state == "held" and device in (None, x.device)), key=lambda x: x.seq)

    def waiting(self, device: int | None = None) -> list[Lease]:
        """In the order they would be granted: class, then arrival."""
        return sorted((x for x in self.leases.values() if x.state == "waiting" and device in (None, x.device)), key=lambda x: (RANK[x.cls], x.seq))

    def busy_for(self, group: str, device: int = 0) -> bool:
        """Whether a new lease of `group` would wait: another group holds the slot, or work is waiting."""
        if not self.enabled:
            return False
        return bool(self.waiting(device)) or any(x.group != group for x in self.held(device))

    def on_grant(self, service: str, fn: Callable[[], Any]) -> None:
        """Run `fn` (async) when `service` is next granted the slot: a proxied trigger's room, made when the mod's
        GPU work can start instead of while it waits (utils/memory/triggers.py)."""
        self._on_grant[service] = (self.clock() + ROOM_PENDING_S, fn)

    async def granted(self, lease: Lease) -> None:
        """The acquire route is about to answer `granted`: run what waited for this mod's turn."""
        until, fn = self._on_grant.pop(lease.service, (0.0, None))
        if fn is None or until < self.clock():
            return
        try:
            await fn()
        except Exception as e:  # noqa: BLE001: the work goes ahead; the mod asks for its own memory as it loads
            log.warning("making room for %s at its GPU turn: %s", lease.service, e)
            if self.activity:
                await self.activity.add(f"Couldn't make room for {self.name_of(lease.service)} when its GPU turn came: {e}",
                                        service=lease.service, level="warn")

    def estimate(self, lease: Lease) -> float | None:
        if lease.est_s is not None:
            return lease.est_s
        past = self.holds.get(lease.service)
        return round(sum(past) / len(past), 1) if past else None

    def remaining(self, lease: Lease) -> float | None:
        est = self.estimate(lease)
        if est is None:
            return None
        if lease.state != "held" or lease.granted_ts is None:
            return est
        return max(0.0, round(est - (time.time() - lease.granted_ts), 1))

    def ahead_of(self, lease: Lease) -> list[dict[str, Any]]:
        """What runs before a waiting lease: the holders, then the waiting leases before it."""
        out = [{"id": x.id, "service": x.service, "label": x.label, "state": "held", "eta_s": self.remaining(x)}
               for x in self.held(lease.device) if x.parent is None]
        for x in self.waiting(lease.device):
            if x is lease:
                break
            out.append({"id": x.id, "service": x.service, "label": x.label, "state": "waiting", "eta_s": self.estimate(x)})
        return out

    @staticmethod
    def eta(ahead: list[dict[str, Any]]) -> float | None:
        """Seconds until a waiting lease starts: the longest holder's remaining time plus the waiting ones'."""
        if not ahead or any(a["eta_s"] is None for a in ahead):
            return None if ahead else 0.0
        held = [a["eta_s"] for a in ahead if a["state"] == "held"]
        return round((max(held) if held else 0.0) + sum(a["eta_s"] for a in ahead if a["state"] == "waiting"), 1)

    def lease_view(self, lease: Lease) -> dict[str, Any]:
        d = lease.view()
        d["name"] = self.name_of(lease.service)
        if lease.state == "held":
            d["elapsed_s"] = round(time.time() - (lease.granted_ts or time.time()), 1)
            d["eta_s"] = self.remaining(lease)
        elif lease.state == "waiting":
            ahead = self.ahead_of(lease)
            d["ahead"] = ahead
            d["eta_s"] = self.eta(ahead)
            d["waited_s"] = round(time.time() - lease.created_ts, 1)
        return d

    def view(self) -> dict[str, Any]:
        held = self.held(0)
        out = {
            "queue": self.enabled, "lease_ttl_s": self.ttl,
            "holder": {"group": self.group, "leases": [self.lease_view(x) for x in held]} if held else None,
            "waiting": [self.lease_view(x) for x in self.waiting(0)],
            "recent": list(reversed(self.history)),
        }
        others = sorted({x.device for x in self.leases.values()} - {0})
        if others:     # plan 36.3: the other GPUs' slots (the first stays in holder and waiting)
            out["devices"] = [{"device": d, "holder": {"group": self.groups.get(d), "leases": [self.lease_view(x) for x in self.held(d)]} if self.held(d) else None,
                               "waiting": [self.lease_view(x) for x in self.waiting(d)]} for d in others]
        return out

    def get(self, lease_id: str) -> Lease:
        lease = self.leases.get(lease_id)
        if lease is None:
            raise GpuError(404, "gpu_lease_unknown", f"no GPU lease {lease_id!r} (it ended, expired or the hub restarted)")
        return lease

    # changing -------------------------------------------------------------------------------

    def register(self, service: str, cls: str = "job", label: str = "", group: str | None = None,
                 est_s: float | None = None, parent: str | None = None, thread: str | None = None,
                 call_id: str | None = None, lease_id: str | None = None, device: int = 0) -> Lease:
        """Add a lease (or find the caller's own, to keep its place) and grant what can be granted."""
        if cls not in RANK:
            raise GpuError(422, "invalid_request", f"class must be one of {', '.join(CLASSES)}")
        if lease_id and lease_id in self.leases:
            lease = self.leases[lease_id]
            lease.touched = self.clock()
            return lease
        par = self.leases.get(parent or "")
        lease = Lease(id=lease_id or new_id(), service=service, group=group or service, cls=cls, label=label or service,
                      est_s=est_s, thread=thread, call_id=call_id, parent=parent, device=par.device if par else device,
                      seq=next(self._seq), touched=self.clock())
        self.leases[lease.id] = lease
        self.pump()
        if lease.state == "waiting":
            self._publish("waiting", lease)
        return lease

    async def acquire(self, wait: float = 0.0, **kw: Any) -> Lease:
        """`register`, then wait up to `wait` seconds for the grant."""
        lease = self.register(**kw)
        if lease.state == "waiting" and wait > 0:
            lease.polling += 1
            try:
                await asyncio.wait_for(lease.granted.wait(), timeout=min(wait, WAIT_MAX_S))
            except TimeoutError:
                pass
            finally:
                lease.polling -= 1
                lease.touched = self.clock()
        return lease

    def renew(self, lease_id: str, info: dict[str, Any] | None = None) -> Lease:
        """Keep a lease alive. One the hub doesn't know (a hub restart, or it expired while the mod stalled) is
        re-registered from `info` (`service`, `group`, `class`, `label`, …): held if the slot is free or held by
        its group (or its parent), else waiting."""
        lease = self.leases.get(lease_id)
        if lease is not None:
            lease.touched = self.clock()
            lease.renewed_ts = time.time()
            return lease
        if not info or not info.get("service"):
            raise GpuError(404, "gpu_lease_unknown", f"no GPU lease {lease_id!r}; send service, class and label to re-register it")
        cls = info.get("class") or "job"
        if cls not in RANK:
            raise GpuError(422, "invalid_request", f"class must be one of {', '.join(CLASSES)}")
        lease = Lease(id=lease_id, service=info["service"], group=info.get("group") or info["service"], cls=cls,
                      label=info.get("label") or info["service"], est_s=info.get("est_s"), thread=info.get("thread"),
                      call_id=info.get("call_id"), parent=info.get("parent"), device=int(info.get("device") or 0),
                      seq=next(self._seq), touched=self.clock())
        parent = self.leases.get(lease.parent or "")
        if parent:
            lease.device = parent.device
        self.leases[lease.id] = lease
        d = lease.device
        if not self.enabled or not self.held(d) or self.groups.get(d) == lease.group or (parent and parent.state == "held"):
            self._grant(lease, note="re-registered")
        else:
            self._publish("waiting", lease)
            log.warning("re-registered GPU lease %s (%s) waits: %s holds GPU %d's slot", lease.id, lease.service, self.groups.get(d), d)
        return lease

    def release(self, lease_id: str) -> Lease | None:
        lease = self.leases.get(lease_id)
        if lease is None:
            return None
        self._end(lease, "released")
        return lease

    def cancel(self, lease_id: str) -> Lease:
        lease = self.get(lease_id)
        if lease.state == "held":
            raise GpuError(409, "gpu_lease_held", f"{self.name_of(lease.service)} is already running {lease.label!r} on the GPU; "
                           "a running job can't be stopped from the queue (cancel it on its mod's page)")
        self._end(lease, "cancelled")
        return lease

    def sweep(self) -> None:
        now, ttl = self.clock(), self.ttl
        for lease in list(self.leases.values()):
            if lease.state == "held" and now - lease.touched > ttl:
                name = self.name_of(lease.service)
                log.warning("GPU lease %s of %s (%s) expired: no renewal for %.0fs", lease.id, lease.service, lease.label, ttl)
                if self.alerts:
                    self.alerts.set(ALERT, "warn", f"{name} held the GPU ({lease.label}) but stopped renewing its lease; "
                                    f"the slot was freed after {ttl:.0f}s", service=lease.service,
                                    action={"label": "Open", "route": f"#/s/{lease.service}"})
                    self._alerted = lease.service
                if self.activity:
                    asyncio.get_running_loop().create_task(self.activity.add(
                        f"{name}'s GPU lease expired ({lease.label}): the slot was freed", service=lease.service, level="warn"))
                self._end(lease, "expired")
            elif lease.state == "waiting" and not lease.polling and now - lease.touched > ttl:
                self._end(lease, "expired")

    def pump(self) -> None:
        """Grant every lease that may run now, on each device."""
        waiting = self.waiting()
        if not self.enabled:
            for x in waiting:
                self._grant(x)
            return
        for x in waiting:                                    # nested work runs under its parent
            parent = self.leases.get(x.parent or "")
            if parent is not None and parent.state == "held":
                self._grant(x)
        for d in sorted({x.device for x in self.waiting()} | set(self.groups)):
            waiting = self.waiting(d)
            if not self.held(d):
                self.groups.pop(d, None)
                if not waiting:
                    continue
                self._grant(waiting[0])
                waiting = self.waiting(d)
            group = self.groups.get(d)
            for x in waiting:                                # the holder's group shares, unless that would jump the queue
                if x.group == group and not any(o.group != group and RANK[o.cls] <= RANK[x.cls] for o in waiting):
                    self._grant(x)

    def _grant(self, lease: Lease, note: str = "") -> None:
        lease.state, lease.granted_ts, lease.renewed_ts = "held", time.time(), time.time()
        lease.touched = self.clock()
        self.groups.setdefault(lease.device, lease.group)
        lease.granted.set()
        self.stats.append((lease.service, "wait", lease.granted_ts - lease.created_ts))
        if self.alerts and self._alerted == lease.service:      # the mod is back: its old lease's alert is done
            self.alerts.clear(ALERT)
            self._alerted = None
        self._publish("granted", lease, note)

    def _end(self, lease: Lease, how: str) -> None:
        if self.leases.pop(lease.id, None) is None:
            return
        was = lease.state
        lease.state, lease.ended_ts = how, time.time()
        lease.granted.set()   # wake a poller: it reads the state
        rec = {**lease.view(), "name": self.name_of(lease.service),
               "wait_s": round((lease.granted_ts or lease.ended_ts) - lease.created_ts, 1)}
        if was == "held" and lease.granted_ts is not None:
            rec["run_s"] = round(lease.ended_ts - lease.granted_ts, 1)
            self.stats.append((lease.service, "hold", rec["run_s"]))
            if how == "released" and lease.parent is None:
                self.holds.setdefault(lease.service, deque(maxlen=HOLDS_KEPT)).append(rec["run_s"])
        self.history.append(rec)
        if not self.held(lease.device):
            self.groups.pop(lease.device, None)
        self._publish(how, lease)
        self.pump()

    def _publish(self, event: str, lease: Lease, note: str = "") -> None:
        ev: dict[str, Any] = {"type": "gpu", "event": event, "lease": self.lease_view(lease) if lease.id in self.leases else
                              {**lease.view(), "name": self.name_of(lease.service)}, "gpu": self.view()}
        if note:
            ev["note"] = note
        self.bus.publish(ev)

    def drain_stats(self) -> list[tuple[str, str, float]]:
        out, self.stats = self.stats, []
        return out


def gpu_note(body: Any, name_of: Callable[[str], str] = lambda s: s) -> str | None:
    """A mod's job waiting for the slot (`stage: "waiting_gpu"`, `ahead`, `eta_s`) as one line for a chat step
    or a job row: "Waiting for the GPU: 3D Generate (model), about 4 min"."""
    if not isinstance(body, dict) or body.get("stage") != "waiting_gpu":
        return None
    ahead = body.get("ahead") if isinstance(body.get("ahead"), list) else []
    first = next((a for a in ahead if isinstance(a, dict) and a.get("service")), None)
    what = ""
    if first:
        label = str(first.get("label") or "").strip()
        what = f": {name_of(str(first['service']))}" + (f" ({label[:60]})" if label else "")
        if len(ahead) > 1:
            what += f" and {len(ahead) - 1} more"
    eta = body.get("eta_s")
    if isinstance(eta, (int, float)) and not isinstance(eta, bool) and eta > 0:
        what += f", about {max(1, round(eta / 60))} min" if eta >= 90 else f", about {round(eta)} s"
    return f"Waiting for the GPU{what}"
