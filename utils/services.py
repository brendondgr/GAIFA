"""The mod supervisor: one `Service` per manifest, and the state machine that runs it (plan 2.3).

    stopped ──start──► starting ──health ok──► ready ◄──► degraded (2 misses)
       ▲                  │                      │            │
       │               timeout / exit         exit / 5 misses │
       │                  ▼                      ▼            ▼
       └──stop── stopping ◄──stop── failed ◄─────────────────┘
                                      │ restart = "on-failure": 2 / 4 / 8 s, ≤ 3 per 5 min
                                      └──────────► starting

Start and stop return quickly; the health wait and the backend stop run as
tasks, and every change is published as a `service` event. A per-service
generation number makes stale tasks give up once a newer start or stop has
happened.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import httpx

from utils import manifest as mf
from utils import status
from utils.backends.base import Backend, BackendError, LogLine, UnitState
from utils.config import Config
from utils.events import ActivityLog, Alerts, EventBus
from utils.paths import Paths
from utils.proc import owner_text, port_listening, port_owner

log = logging.getLogger("aihub.services")

ServiceState = Literal["stopped", "starting", "ready", "degraded", "stopping", "failed"]
LoadState = Literal["unloaded", "loading", "loaded", "unloading", "n/a"]
GB = 1024**3
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
    started_ts: float | None = None
    command: list[str] = field(default_factory=list)
    health: dict[str, Any] | None = None
    status: dict[str, Any] | None = None
    status_ts: float | None = None
    last_error: str | None = None
    in_flight: int = 0
    last_request_ts: float | None = None
    misses: int = 0
    restarts: deque[float] = field(default_factory=lambda: deque(maxlen=10))
    gen: int = 0
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
        return self.eff.port

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


class ServiceManager:
    def __init__(
        self,
        paths: Paths,
        config: Config,
        backend: Backend,
        bus: EventBus,
        activity: ActivityLog,
        alerts: Alerts,
        hub_port: int,
        extra_dirs: list[Path] | None = None,
        timing: Timing | None = None,
    ) -> None:
        self.paths, self.config, self.backend = paths, config, backend
        self.bus, self.activity, self.alerts = bus, activity, alerts
        self.hub_port = hub_port
        self.dirs = [paths.services, *(extra_dirs or [])]
        self.t = timing or Timing()
        self.services: dict[str, Service] = {}
        self.client = httpx.AsyncClient(trust_env=False, timeout=self.t.health_timeout_s)
        self._closing = False
        self._boot_task: asyncio.Task[None] | None = None
        # Hooks for later steps: operations (2.6) refetch on ready, memory triggers (5.5).
        self.on_ready: list[Callable[[Service], Awaitable[None]]] = []

    # --- discovery ------------------------------------------------------------------

    def discover(self) -> None:
        mods = mf.discover(self.dirs, self.hub_port)
        clashes = mf.check_effective_ports(mods, self.config, self.hub_port)
        services: dict[str, Service] = {}
        for mod in mf.ordered(mods, self.config.services.order):
            errors = list(mod.errors)
            if mod.id in clashes and not errors:
                errors.append(f"config.toml: [services.{mod.id}] {clashes[mod.id]}")
            svc = Service(mod=mod, eff=mf.effective(mod, self.config), errors=errors)
            svc.load = self._idle_load(svc)
            if errors:
                svc.state = "failed"
            services[mod.id] = svc
        self.services = services

    def get(self, service_id: str) -> Service:
        svc = self.services.get(service_id)
        if svc is None:
            raise ServiceError(404, "service_not_found", f"no mod named {service_id!r} (looked in services/)")
        return svc

    def list(self) -> list[Service]:
        return list(self.services.values())

    def reconfigure(self, config: Config) -> None:
        """Apply a new config.toml: enabled, autostart and the rest take effect now; port and env on the next start."""
        self.config = config
        clashes = mf.check_effective_ports([s.mod for s in self.services.values()], config, self.hub_port)
        for svc in self.services.values():
            svc.eff = mf.effective(svc.mod, config)
            svc.errors = list(svc.mod.errors)
            if svc.id in clashes and not svc.errors:
                svc.errors.append(f"config.toml: [services.{svc.id}] {clashes[svc.id]}")
            self._publish(svc)

    # --- boot and shutdown ----------------------------------------------------------------

    async def boot(self, autostart: bool = True) -> None:
        """Adopt running units, note ones that failed while the hub was down, then autostart in the background."""
        self.discover()
        try:
            ours = set(await self.backend.list_ours())
        except BackendError as e:
            log.warning("can't list running mods: %s", e)
            ours = set()
        for sid in sorted(ours - set(self.services)):
            await self._stop_orphan(sid)
        for svc in self.services.values():
            if svc.errors:
                continue
            if svc.external:
                self._spawn(svc, self._watch_external(svc, svc.gen))
                continue
            if svc.id in ours:
                if await self._ours(svc.id):
                    await self._adopt(svc)
                else:
                    self._set(svc, "failed", error=f"a unit named {svc.id} is running from another AIHub folder; stop it there first")
                continue
            try:
                st = await self.backend.state(svc.id)
            except BackendError:
                continue
            if st.active == "failed":
                tail = await self._tail(svc)
                self._set(svc, "failed", error=f"{st.describe_exit()} while AIHub was down" + tail)
        if autostart:
            self._boot_task = asyncio.create_task(self._autostart())

    async def _ours(self, sid: str) -> bool:
        """True when the running unit was started from this hub's root (not a second checkout's)."""
        try:
            workdir = await self.backend.workdir(sid)
        except BackendError:
            return False
        return bool(workdir) and any(Path(workdir).is_relative_to(d) for d in [self.paths.root, *self.dirs])

    async def _stop_orphan(self, sid: str) -> None:
        """A running unit with no folder: stop it, but only if it ran from this hub's root."""
        if not await self._ours(sid):
            log.warning("%s is running from outside this hub's root; leaving it alone", sid)
            return
        log.warning("stopping %s: it is running but services/%s no longer exists", sid, sid)
        try:
            await self.backend.stop(sid, 30)
        except BackendError as e:
            log.warning("can't stop orphan %s: %s", sid, e)
            return
        await self.activity.add(f"Stopped {sid}: its folder was removed", service=None, level="warn")

    async def _adopt(self, svc: Service) -> None:
        st = await self.backend.state(svc.id)
        svc.pid, svc.started_ts = st.pid, st.started_ts
        svc.command = self._command(svc)
        svc.gen += 1
        self._set(svc, "starting")
        await self.activity.add(f"Adopted {svc.mod.name}, already running (pid {st.pid})", service=svc.id)
        self._spawn(svc, self._wait_ready(svc, svc.gen, adopted=True))

    async def _autostart(self) -> None:
        tasks: dict[str, asyncio.Task[None]] = {}
        mods = mf.start_order([s.mod for s in self.services.values()], self.config.services.order)
        for mod in mods:
            svc = self.services[mod.id]
            if not (svc.startable and svc.eff.enabled and svc.eff.autostart) or svc.external or svc.state != "stopped":
                continue
            deps = [tasks[d] for d in (svc.m.run.after if svc.m else []) if d in tasks]
            tasks[svc.id] = asyncio.create_task(self._start_after(svc, deps))
        await asyncio.gather(*tasks.values(), return_exceptions=True)

    async def _start_after(self, svc: Service, deps: list[asyncio.Task[None]]) -> None:
        if deps:
            await asyncio.gather(*deps, return_exceptions=True)
        try:
            await self.start(svc.id, wait=True)
        except ServiceError as e:
            log.warning("autostart %s: %s", svc.id, e.detail)

    async def close(self) -> None:
        self._closing = True
        tasks = [t for s in self.services.values() for t in s.tasks]
        if self._boot_task:
            tasks.append(self._boot_task)
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await self.backend.close()
        await self.client.aclose()

    # --- start / stop / restart ----------------------------------------------------------------

    async def start(self, service_id: str, wait: bool = False) -> Service:
        svc = self.get(service_id)
        self._check_controllable(svc)
        if not svc.startable:
            raise ServiceError(409, "manifest_invalid", f"{svc.id} can't start: {svc.errors[0]}", {"errors": svc.errors})
        if not svc.eff.enabled:
            raise ServiceError(409, "service_disabled", f"{svc.id} is disabled; enable it in Settings or config.toml first")
        async with svc.lock:
            if svc.state in ("starting", "ready", "degraded"):
                pass  # already on its way
            else:
                await self._launch(svc)
        if wait:
            await self._wait_settled(svc)
        return svc

    async def _launch(self, svc: Service) -> None:
        svc.gen += 1
        gen = svc.gen
        self._cancel_tasks(svc)
        try:
            spec = mf.launch_spec(svc.mod, self.config, self.paths, self.hub_port)
        except mf.ManifestError as e:
            self._set(svc, "failed", error=str(e))
            raise ServiceError(409, "manifest_invalid", f"{svc.id} can't start: {e}") from None
        st = await self._backend_state(svc)
        if st.active != "active" and await asyncio.to_thread(port_listening, svc.port):
            owner = await asyncio.to_thread(port_owner, svc.port)
            msg = f"port {svc.port} is already in use by {owner_text(owner)}"
            self._set(svc, "failed", error=msg)
            await self.activity.add(f"{svc.mod.name} can't start: {msg}", service=svc.id, level="error", route=f"#/s/{svc.id}")
            raise ServiceError(409, "port_in_use", f"{svc.id} can't start: {msg}", {"port": svc.port, "owner": owner})
        if st.active == "active":
            await self._adopt(svc)  # running but we lost track (e.g. started by hand): take it over
            return
        self._prepare_dirs(svc, spec)
        svc.command = spec.argv
        svc.health = svc.status = None
        svc.misses = 0
        self._set(svc, "starting")
        try:
            st = await self.backend.start(spec)
        except BackendError as e:
            msg = f"couldn't launch: {e}"
            self._set(svc, "failed", error=msg + await self._tail(svc))
            await self.activity.add(f"{svc.mod.name} failed to launch: {e}", service=svc.id, level="error", route=f"#/s/{svc.id}/logs")
            raise ServiceError(500, "service_failed", f"{svc.id}: {msg}") from None
        svc.pid, svc.started_ts = st.pid, st.started_ts or time.time()
        self._spawn(svc, self._wait_ready(svc, gen))

    def _prepare_dirs(self, svc: Service, spec: mf.LaunchSpec) -> None:
        uses_outputs = bool(svc.m and svc.m.outputs) or any("{outputs}" in v for v in [*(svc.m.run.command if svc.m else []), *(svc.m.run.env.values() if svc.m else [])])
        if uses_outputs:
            spec.outputs.mkdir(parents=True, exist_ok=True)

    async def stop(self, service_id: str, wait: bool = False) -> Service:
        svc = self.get(service_id)
        self._check_controllable(svc)
        if svc.state in ("stopped",) or (svc.state == "failed" and svc.errors):
            return svc
        svc.gen += 1
        gen = svc.gen
        self._cancel_tasks(svc)
        self._set(svc, "stopping")
        task = self._spawn(svc, self._do_stop(svc, gen), cancel_on_restart=False)
        if wait:
            await asyncio.shield(task)
        return svc

    async def _do_stop(self, svc: Service, gen: int) -> None:
        async with svc.lock:
            timeout = svc.m.run.stop_timeout_s if svc.m else 30
            try:
                await self.backend.stop(svc.id, timeout)
            except BackendError as e:
                if gen == svc.gen:
                    self._set(svc, "failed", error=f"couldn't stop: {e}")
                return
            if gen != svc.gen:
                return
            svc.pid = svc.started_ts = None
            self._clear_runtime(svc)
            self._set(svc, "stopped")
            await self.activity.add(f"Stopped {svc.mod.name}", service=svc.id)

    async def restart(self, service_id: str, wait: bool = False) -> Service:
        svc = self.get(service_id)
        self._check_controllable(svc)
        if svc.state not in ("stopped",) and not (svc.state == "failed" and svc.errors):
            await self.stop(service_id, wait=True)
        return await self.start(service_id, wait=wait)

    def _check_controllable(self, svc: Service) -> None:
        if svc.external:
            raise ServiceError(
                409, "external_service",
                f"{svc.id} is an external service (kind = \"external\"): AIHub only checks its health and proxies it; start or stop it where it runs",
            )

    async def _wait_settled(self, svc: Service, timeout: float | None = None) -> None:
        limit = timeout or ((svc.m.run.start_timeout_s if svc.m else 60) + 15)
        deadline = time.monotonic() + limit
        while svc.state in ("starting", "stopping") and time.monotonic() < deadline:
            await asyncio.sleep(0.05)

    # --- health -----------------------------------------------------------------------

    async def check_health(self, svc: Service) -> dict[str, Any]:
        """One health probe: `{ok, latency_ms, body}` (brief `ServiceDetail.health`)."""
        assert svc.m
        t0 = time.perf_counter()
        if svc.m.run.health == "tcp":
            try:
                _, w = await asyncio.wait_for(asyncio.open_connection("127.0.0.1", svc.port), self.t.health_timeout_s)
                w.close()
                return {"ok": True, "latency_ms": round((time.perf_counter() - t0) * 1000, 1), "body": None}
            except (OSError, TimeoutError):
                return {"ok": False, "latency_ms": None, "body": None}
        try:
            r = await self.client.get(svc.url + svc.m.run.health, timeout=self.t.health_timeout_s)
        except httpx.HTTPError as e:
            return {"ok": False, "latency_ms": None, "body": f"{type(e).__name__}: {e}" if str(e) else type(e).__name__}
        ms = round((time.perf_counter() - t0) * 1000, 1)
        body: Any = r.text[:4096]
        if r.headers.get("content-type", "").startswith("application/json"):
            try:
                body = r.json()
            except ValueError:
                pass
        return {"ok": 200 <= r.status_code < 300, "latency_ms": ms, "body": body, "status": r.status_code}

    async def _wait_ready(self, svc: Service, gen: int, adopted: bool = False) -> None:
        assert svc.m
        deadline = time.monotonic() + svc.m.run.start_timeout_s
        while gen == svc.gen:
            st = await self._backend_state(svc)
            if gen != svc.gen:
                return
            if st.active != "active":
                await self._failed(svc, gen, f"{st.describe_exit()} while starting")
                return
            h = await self.check_health(svc)
            if gen != svc.gen:
                return
            svc.health = h
            if h["ok"]:
                svc.misses = 0
                self._set(svc, "ready")
                self.alerts.clear(f"svc-{svc.id}")
                verb = "is ready again" if adopted else "is ready"
                secs = time.time() - (svc.started_ts or time.time())
                await self.activity.add(f"{svc.mod.name} {verb}" + ("" if adopted else f" ({secs:.1f}s)"), service=svc.id)
                for hook in self.on_ready:
                    self._spawn(svc, hook(svc))
                self._spawn(svc, self._monitor(svc, gen))
                if svc.m.run.status:
                    self._spawn(svc, status.poll(self, svc, gen))
                return
            if time.monotonic() > deadline:
                await self._quiet_stop(svc)
                await self._failed(svc, gen, f"not healthy after {svc.m.run.start_timeout_s:g}s ({svc.m.run.health} {_why(h)})", stopped=True)
                return
            await asyncio.sleep(self.t.start_poll_s)

    async def _monitor(self, svc: Service, gen: int) -> None:
        while gen == svc.gen:
            await asyncio.sleep(self.t.health_every_s)
            if gen != svc.gen:
                return
            st = await self._backend_state(svc)
            if gen != svc.gen:
                return
            if st.active != "active":
                await self._failed(svc, gen, st.describe_exit())
                return
            h = await self.check_health(svc)
            if gen != svc.gen:
                return
            svc.health = h
            if h["ok"]:
                if svc.state == "degraded":
                    self._set(svc, "ready")
                    await self.activity.add(f"{svc.mod.name} is healthy again", service=svc.id)
                svc.misses = 0
                continue
            svc.misses += 1
            if svc.misses >= self.t.failed_after:
                await self._quiet_stop(svc)
                await self._failed(svc, gen, f"health check failed {svc.misses} times in a row ({_why(h)})", stopped=True)
                return
            if svc.misses >= self.t.degraded_after and svc.state == "ready":
                self._set(svc, "degraded", error=f"health check failing ({_why(h)})")
                await self.activity.add(f"{svc.mod.name} is not answering its health check", service=svc.id, level="warn", route=f"#/s/{svc.id}/logs")

    async def _failed(self, svc: Service, gen: int, why: str, stopped: bool = False) -> None:
        """A running or starting mod failed: record it, then maybe restart it."""
        tail = await self._tail(svc)
        if gen != svc.gen:
            return
        svc.pid = None
        self._clear_runtime(svc, jobs_end="failed")
        self._set(svc, "failed", error=why + tail)
        self.alerts.set(
            f"svc-{svc.id}", "error", f"{svc.mod.name} failed: {why}", service=svc.id,
            action={"label": "Logs", "route": f"#/s/{svc.id}/logs"},
        )
        await self.activity.add(f"{svc.mod.name} failed: {why}", service=svc.id, level="error", route=f"#/s/{svc.id}/logs")
        if not stopped:  # clear systemd's failed unit / reap leftovers so the next start is clean
            try:
                await self.backend.stop(svc.id, 5)
            except BackendError:
                pass
        if svc.m and svc.m.run.restart == "on-failure" and not self._closing:
            self._spawn(svc, self._maybe_restart(svc, gen), cancel_on_restart=False)

    async def _maybe_restart(self, svc: Service, gen: int) -> None:
        now = time.time()
        recent = [t for t in svc.restarts if now - t < self.t.restart_window_s]
        if len(recent) >= len(self.t.backoff_s):
            mins = self.t.restart_window_s / 60
            svc.last_error = f"{svc.last_error}\n\nGave up after {len(recent)} restarts in {mins:g} min."
            self._publish(svc)
            await self.activity.add(f"{svc.mod.name}: gave up restarting after {len(recent)} tries", service=svc.id, level="error", route=f"#/s/{svc.id}/logs")
            return
        delay = self.t.backoff_s[len(recent)]
        await asyncio.sleep(delay)
        if gen != svc.gen or svc.state != "failed":
            return  # the user started or stopped it meanwhile
        svc.restarts.append(time.time())
        await self.activity.add(f"Restarting {svc.mod.name} (try {len(recent) + 1} of {len(self.t.backoff_s)})", service=svc.id, level="warn")
        try:
            async with svc.lock:
                if gen == svc.gen and svc.state == "failed":
                    await self._launch(svc)
        except ServiceError as e:
            log.warning("restart %s: %s", svc.id, e.detail)

    async def _watch_external(self, svc: Service, gen: int) -> None:
        """External mods: health only. Reachable = ready; unreachable = stopped (never seen) or failed."""
        seen = False
        while gen == svc.gen and not self._closing:
            h = await self.check_health(svc)
            svc.health = h
            if h["ok"]:
                svc.misses = 0
                if svc.state != "ready":
                    seen = True
                    self._set(svc, "ready")
                    for hook in self.on_ready:
                        self._spawn(svc, hook(svc))
                    if svc.m and svc.m.run.status and not any(getattr(t, "status_poll", False) for t in svc.tasks):
                        t = self._spawn(svc, status.poll(self, svc, gen))
                        t.status_poll = True  # type: ignore[attr-defined]
            else:
                svc.misses += 1
                if not seen:
                    if svc.state != "stopped":
                        self._set(svc, "stopped")
                elif svc.misses >= self.t.failed_after and svc.state != "failed":
                    self._set(svc, "failed", error=f"not responding on {svc.url} ({_why(h)})")
                elif svc.misses >= self.t.degraded_after and svc.state == "ready":
                    self._set(svc, "degraded", error=f"health check failing ({_why(h)})")
            await asyncio.sleep(self.t.health_every_s)

    # --- logs -----------------------------------------------------------------------

    async def logs(self, service_id: str, n: int = 200) -> list[LogLine]:
        svc = self.get(service_id)
        if svc.external:
            return []
        try:
            return await self.backend.logs(svc.id, n)
        except BackendError as e:
            raise ServiceError(500, "hub_error", f"can't read logs for {svc.id}: {e}") from None

    async def _tail(self, svc: Service) -> str:
        try:
            lines = await self.backend.logs(svc.id, LOG_TAIL)
        except BackendError:
            return ""
        if not lines:
            return ""
        return "\n\nLast log lines:\n" + "\n".join(ln["text"] for ln in lines)

    # --- helpers -------------------------------------------------------------------------

    async def _quiet_stop(self, svc: Service) -> None:
        try:
            await self.backend.stop(svc.id, svc.m.run.stop_timeout_s if svc.m else 30)
        except BackendError as e:
            log.warning("stop %s: %s", svc.id, e)

    def _command(self, svc: Service) -> list[str]:
        try:
            return mf.launch_spec(svc.mod, self.config, self.paths, self.hub_port).argv
        except mf.ManifestError:
            return list(svc.m.run.command) if svc.m else []

    async def _backend_state(self, svc: Service) -> UnitState:
        try:
            return await self.backend.state(svc.id)
        except BackendError as e:
            log.warning("state of %s: %s", svc.id, e)
            return UnitState("active", pid=svc.pid, started_ts=svc.started_ts)  # assume unchanged

    def _idle_load(self, svc: Service) -> LoadState:
        return "unloaded" if svc.has_memory else "n/a"

    def _clear_runtime(self, svc: Service, jobs_end: str = "cancelled") -> None:
        for job in svc.jobs:  # jobs can't outlive their process
            if job["state"] in status.ACTIVE_JOBS:
                self.bus.publish({"type": "job", "job": {**job, "state": jobs_end}})
        svc.health = svc.status = svc.status_ts = None
        svc.stats = []
        svc.memory_estimate_gb = None
        svc.busy, svc.idle_s, svc.jobs = False, None, []
        svc.load = self._idle_load(svc)
        svc.misses = 0
        svc.in_flight = 0

    def _set(self, svc: Service, state: ServiceState, error: str | None = None) -> None:
        if state != svc.state:
            svc.state = state
            svc.state_since = time.time()
        if state in ("ready", "stopped"):
            svc.last_error = None  # "starting" keeps the previous error visible during a restart
        if error is not None:
            svc.last_error = error
        if state == "stopped":
            self.alerts.clear(f"svc-{svc.id}")
        self._publish(svc)

    def _publish(self, svc: Service) -> None:
        if self._closing:
            return
        from utils.service_views import summary

        self.bus.publish({"type": "service", "service": summary(self, svc)})

    def _spawn(self, svc: Service, coro: Awaitable[Any], cancel_on_restart: bool = True) -> asyncio.Task[Any]:
        task = asyncio.ensure_future(coro)
        svc.tasks.add(task)
        task.add_done_callback(svc.tasks.discard)
        task.add_done_callback(_log_task_error)
        if not cancel_on_restart:
            # Stop and restart-after-failure tasks outlive a new start or stop (they check `gen`),
            # but still end with the hub.
            task.keep = True  # type: ignore[attr-defined]
        return task

    def _cancel_tasks(self, svc: Service) -> None:
        current = asyncio.current_task()
        for t in list(svc.tasks):
            if t is not current and not getattr(t, "keep", False):
                t.cancel()


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
