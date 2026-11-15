"""Finding mods and taking over running ones: boot, adoption, autostart and rescan."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

from utils import manifest as mf
from utils.backends.base import BackendError
from utils.config import Config
from utils.services.model import Service, ServiceError, log

if TYPE_CHECKING:
    from utils.services.manager import ServiceManager

    _Base = ServiceManager
else:
    _Base = object


class DiscoveryMixin(_Base):
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
        for svc in services.values():     # capability-enablement 1.2: said wherever last_error shows
            if not svc.errors and not self.installed(svc):
                svc.last_error = f"not set up: run `gaifa setup {svc.id}`"
        self._manifest_alerts()

    def _manifest_alerts(self) -> None:
        """One alert per mod whose service.toml (or its config.toml override) is broken (plan 6.4)."""
        want = {f"manifest-{s.id}": s for s in self.services.values() if s.errors}
        for aid, svc in want.items():
            more = f" (+{len(svc.errors) - 1} more)" if len(svc.errors) > 1 else ""
            self.alerts.set(aid, "error", f"Mod \"{svc.id}\" has a manifest error: {svc.errors[0]}{more}", service=svc.id,
                            action={"label": "Show details", "route": f"#/s/{svc.id}/settings"})
        for a in self.alerts.list():
            if a["id"].startswith("manifest-") and a["id"] not in want:
                self.alerts.clear(a["id"])

    async def rescan(self, autostart: bool = True) -> dict[str, list[str]]:
        """Pick up added, removed and edited mod folders without restarting the hub.

        Added mods autostart like at boot; removed ones are stopped; an edited manifest
        applies at the mod's next start. Running mods are otherwise left alone.
        """
        mods = mf.discover(self.dirs, self.hub_port)
        clashes = mf.check_effective_ports(mods, self.config, self.hub_port)
        found = {m.id: m for m in mods}
        added: list[str] = []
        removed: list[str] = []
        changed: list[str] = []
        for sid in [s for s in self.services if s not in found]:
            svc = self.services[sid]
            if not svc.external and svc.state not in ("stopped",) and not svc.errors:
                await self.stop(sid, wait=True)
            svc.gen += 1
            self._cancel_tasks(svc)
            for t in list(svc.tasks):
                t.cancel()
            del self.services[sid]
            removed.append(sid)
            await self.activity.add(f"Removed {svc.mod.name}: its folder is gone", service=None)
        for mod in mods:
            errors = list(mod.errors)
            if mod.id in clashes and not errors:
                errors.append(f"config.toml: [services.{mod.id}] {clashes[mod.id]}")
            svc = self.services.get(mod.id)
            if svc is None:
                svc = Service(mod=mod, eff=mf.effective(mod, self.config), errors=errors)
                svc.load = self._idle_load(svc)
                svc.state = "failed" if errors else "stopped"
                if not errors and not self.installed(svc):   # capability-enablement 1.2: said wherever last_error shows
                    svc.last_error = f"not set up: run `gaifa setup {svc.id}`"
                self.services[mod.id] = svc
                added.append(mod.id)
                await self.activity.add(f"Found a new mod: {mod.name}", service=mod.id, route=f"#/s/{mod.id}")
                if svc.external and not errors:
                    self._spawn(svc, self._watch_external(svc, svc.gen))
                continue
            if mod.raw != svc.mod.raw or errors != svc.errors:
                svc.mod, svc.errors = mod, errors
                svc.eff = mf.effective(mod, self.config)
                if errors and svc.state == "stopped":
                    svc.state = "failed"
                elif not errors and svc.state == "failed" and not svc.pid:
                    svc.state, svc.last_error = "stopped", None
                changed.append(mod.id)
                self._publish(svc)
        order = [m.id for m in mf.ordered([s.mod for s in self.services.values()], self.config.services.order)]
        self.services = {sid: self.services[sid] for sid in order}
        self._manifest_alerts()
        if added or removed:
            self.bus.publish({"type": "resync"})  # the UI refetches the service list
        if autostart and added:
            for mod in mf.start_order([self.services[i].mod for i in added], self.config.services.order):
                svc = self.services[mod.id]
                if svc.startable and svc.eff.enabled and svc.eff.autostart and not svc.external:
                    if not self.installed(svc):     # capability-enablement 1.3: nothing to start until it's set up
                        log.info("autostart %s: not set up", svc.id)
                        continue
                    self._spawn(svc, self._start_quietly(svc.id))
        return {"added": added, "removed": removed, "changed": changed}

    async def _start_quietly(self, service_id: str) -> None:
        try:
            await self.start(service_id, wait=True)
        except ServiceError as e:
            log.warning("autostart %s: %s", service_id, e.detail)

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
        self._manifest_alerts()

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
                    self._set(svc, "failed", error=f"a unit named {svc.id} is running from another GAIFA folder; stop it there first")
                continue
            try:
                st = await self.backend.state(svc.id)
            except BackendError:
                continue
            if st.active == "failed":
                tail = await self._tail(svc)
                self._set(svc, "failed", error=f"{st.describe_exit()} while GAIFA was down" + tail)
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
        svc.live_port = svc.eff.port  # adopted: assume the configured port (it was started with it)
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
            why = self.unavailable(svc)
            if why:                       # plan 38.3: its variant's accel isn't on this machine
                svc.last_error = f"unavailable: {why}"
                log.info("autostart %s: unavailable (%s)", svc.id, svc.eff.accel)
                continue
            if not self.installed(svc):   # a fresh clone: nothing to start until it's set up (plan 23.12)
                svc.last_error = f"not set up: run `gaifa setup {svc.id}`"
                log.info("autostart %s: not set up", svc.id)
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

