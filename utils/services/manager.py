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
import shutil
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import httpx

from utils import manifest as mf
from utils import operations
from utils.backends.base import Backend, BackendError, LogLine, UnitState
from utils.config import Config
from utils.events import ActivityLog, Alerts, EventBus
from utils.paths import Paths
from utils.proc import owner_text, port_listening, port_owner
from utils.services import status
from utils.services.discovery import DiscoveryMixin
from utils.services.health import HealthMixin
from utils.services.model import LOG_TAIL, LoadState, Service, ServiceError, ServiceState, Timing, _log_task_error, log


class ServiceManager(DiscoveryMixin, HealthMixin):
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
        self.registry: Any = None  # utils.registry.Registry, set by the lifespan: ServiceDetail.models
        self.memory: Any = None  # utils.memory.MemoryManager, set by the lifespan: load rule, measured use
        self.client = httpx.AsyncClient(trust_env=False, timeout=self.t.health_timeout_s)
        from utils.proxy import make_client

        self.proxy_client = make_client()
        self.before_proxy: list[Callable[[Service, str, str, Any], Awaitable[None]]] = []  # (svc, method, path, headers): memory triggers (5.5)
        self._closing = False
        self._boot_task: asyncio.Task[None] | None = None
        # Hooks for later steps: operations (2.6) refetch on ready, memory triggers (5.5).
        self.on_ready: list[Callable[[Service], Awaitable[None]]] = [lambda svc: operations.refresh(self, svc)]
        self.logfiles: Any = None   # logfiles.LogFiles (plan 16.1), set by the hub

    def get(self, service_id: str) -> Service:
        svc = self.services.get(service_id)
        if svc is None:
            raise ServiceError(404, "service_not_found", f"no mod named {service_id!r} (looked in services/)")
        return svc

    def list(self) -> list[Service]:
        return list(self.services.values())

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
        await self.proxy_client.aclose()

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
        svc.live_port = spec.port
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
            svc.pid = svc.started_ts = svc.live_port = None
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

    # --- logs -----------------------------------------------------------------------

    async def logs(self, service_id: str, n: int = 200) -> list[LogLine]:
        svc = self.get(service_id)
        if svc.external:
            return []
        if self.logfiles is not None:     # data/logs/<id>.log (plan 16.1); the backend until it has lines
            lines = await asyncio.to_thread(self.logfiles.read, svc.id, n)
            if lines:
                return lines
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

    def installed(self, svc: Service) -> bool:
        """The mod's command exists (its venv, binary or script): it has been set up (plan 23.12).
        Only the first word is checked, so `bash run.sh` counts as installed."""
        argv = self._command(svc)
        if svc.external or not argv:
            return True
        exe = argv[0]
        if "/" in exe:
            p = Path(exe)
            return (p if p.is_absolute() else svc.mod.dir / p).exists()
        return shutil.which(exe) is not None

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
        from utils.services.views import summary

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

