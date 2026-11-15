"""Health: waiting for a mod to get ready, watching it, and restarting it on failure."""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

import httpx

from utils.backends.base import BackendError
from utils.services import status
from utils.services.model import Service, ServiceError, _why, log

if TYPE_CHECKING:
    from utils.services.manager import ServiceManager

    _Base = ServiceManager
else:
    _Base = object


class HealthMixin(_Base):
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
                svc.start_failed_at = time.time()   # capability-enablement 1.3
                await self._failed(svc, gen, f"{st.describe_exit()} while starting")
                return
            h = await self.check_health(svc)
            if gen != svc.gen:
                return
            svc.health = h
            if h["ok"]:
                svc.misses = 0
                svc.start_failed_at = None
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
                svc.start_failed_at = time.time()
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
        svc.pid = svc.live_port = None
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

