"""The hub's watch over the mods that are their own repositories (plan mod-repos 3.3).

At start (`[repos] check_on_start`) and after every fetch, it reads each submodule's state and keeps
the alerts in step: one per problem, `repos.<id>.<code>`, cleared once the problem is gone. Warnings
and errors are alerts; with `notify = "all"`, info (updates, unpinned commits, a failed fetch) too.
New commits on a branch also go to the activity log once. Every `fetch_every_h` hours it fetches
(the only network it uses; 0 = never). An update runs in a thread with progress events
(`{type: "repos", …}`) and its last result is kept for `GET /api/repos`.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from utils import repos, repos_update
from utils.services.status import ACTIVE_JOBS

log = logging.getLogger("gaifa.repos")
TICK_S = 60.0


class RepoWatcher:
    def __init__(self, hub: Any) -> None:
        self.hub = hub
        self.states: list[repos.RepoState] = []
        self.update_job: dict[str, Any] | None = None    # {id, running, steps, result}
        self._seen_behind: dict[str, int] = {}
        self._task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    @property
    def root(self):
        return self.hub.paths.root

    @property
    def cfg(self):
        return self.hub.config.repos

    # ---- state and alerts ---------------------------------------------------------------------

    async def refresh(self) -> list[repos.RepoState]:
        async with self._lock:
            self.states = await asyncio.to_thread(repos.list_states, self.root)
            await self._sync_alerts()
            return self.states

    async def _sync_alerts(self) -> None:
        notify = self.cfg.notify
        want: dict[str, tuple[str, str, str]] = {}
        for st in self.states:
            for p in st.problems:
                if notify == "off" or (p.level == "info" and notify != "all"):
                    continue
                level = "error" if p.level == "error" else "warn"
                want[f"repos.{st.id}.{p.code}"] = (level, f"{p.title}. Fix: {p.fix}" if p.fix else p.title, st.id)
            if st.behind and st.behind > self._seen_behind.get(st.id, 0):
                await self.hub.activity.add(f"{st.id}: {st.behind} new commit{'s' * (st.behind != 1)} on {st.branch} "
                                            f"({st.url})", service=st.id, route="#/settings/services/repositories")
            self._seen_behind[st.id] = st.behind
        for alert in list(self.hub.alerts.list()):
            if alert["id"].startswith("repos.") and alert["id"] not in want:
                self.hub.alerts.clear(alert["id"])
        for aid, (level, text, sid) in want.items():
            self.hub.alerts.set(aid, level, text, service=sid, action={"label": "Repositories", "route": "#/settings/services/repositories"})

    async def fetch(self, sid: str | None = None) -> list[repos.RepoState]:
        ids = [sid] if sid else [s[0] for s in repos.submodules(self.root)]
        for i in ids:
            await asyncio.to_thread(repos.fetch, self.root, i)
        return await self.refresh()

    def last_fetch(self) -> float | None:
        stamps = [s.last_fetch_ts for s in self.states if s.last_fetch_ts]
        return min(stamps) if stamps else None

    def due(self, now: float | None = None) -> bool:
        every = self.cfg.fetch_every_h
        if not every or not self.states:
            return False
        last = self.last_fetch()
        return last is None or (now or time.time()) - last >= every * 3600

    # ---- the loop -----------------------------------------------------------------------------

    async def start(self) -> None:
        if self.cfg.check_on_start:
            try:
                await self.refresh()
            except Exception:  # noqa: BLE001 — a broken checkout must not stop the hub
                log.exception("reading the repositories' state")
        self._task = asyncio.create_task(self._loop())

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(TICK_S)
            try:
                if not self.states:
                    await self.refresh()
                if self.due():
                    await self.fetch()
            except Exception:  # noqa: BLE001
                log.exception("watching the repositories")

    async def close(self) -> None:
        if self._task:
            self._task.cancel()

    # ---- an update, in a thread -----------------------------------------------------------------

    def hooks(self, loop: asyncio.AbstractEventLoop, sid: str) -> repos_update.Hooks:
        hub = self.hub

        def run(coro: Any, timeout: float = 900) -> Any:
            return asyncio.run_coroutine_threadsafe(coro, loop).result(timeout)

        def svc(i: str) -> Any:
            return hub.services.services.get(i)

        def install(i: str) -> int:
            from utils import cli_mods
            return cli_mods.run_install(self.root / "services" / i)

        def check(i: str) -> tuple[bool | None, str]:
            from utils.services import check as checks
            s = svc(i)
            if s is None:
                return False, f"the hub doesn't know {i} (gaifa rescan)"
            r = run(checks.run(hub.services, s))
            failed = [f"{c['name']}: {c['detail']}" for c in r["checks"] if c["status"] == "fail"]
            return not failed, "; ".join(failed) or "all checks passed"

        def busy(i: str) -> str | None:
            s = svc(i)
            if s is None:
                return None
            jobs = [j for j in s.jobs if j.get("state") in ACTIVE_JOBS]
            return f"{len(jobs)} job(s): " + ", ".join(j.get("label", "?") for j in jobs[:3]) if jobs else None

        def tests() -> tuple[bool, str]:
            import subprocess
            r = subprocess.run(["uv", "run", "pytest", "-q", "-x"], cwd=self.root, capture_output=True, text=True, timeout=1800)
            return r.returncode == 0, (r.stdout.strip().splitlines() or [""])[-1]

        def progress(msg: str) -> None:
            if self.update_job is not None:
                self.update_job["steps"].append({"ts": time.time(), "text": msg})
            loop.call_soon_threadsafe(hub.bus.publish, {"type": "repos", "id": sid, "step": msg})

        return repos_update.Hooks(
            install=install, check=check, busy=busy, tests=tests, progress=progress,
            reload=lambda i: run(hub.services.rescan(autostart=False)) and None,
            running=lambda i: bool(svc(i)) and svc(i).state in ("ready", "starting", "unhealthy"),
            restart=lambda i: run(hub.services.restart(i, wait=True)) and None)

    def busy_updating(self) -> bool:
        return bool(self.update_job and self.update_job["running"])

    async def update(self, sid: str, to: str | None = None, commit: bool = False, force_busy: bool = False) -> dict[str, Any]:
        """Start an update in the background; its steps and result go to `update_job` and the bus."""
        self.update_job = {"id": sid, "running": True, "steps": [], "result": None, "started": time.time()}
        loop = asyncio.get_running_loop()
        hooks = self.hooks(loop, sid)

        async def go() -> None:
            try:
                res = await asyncio.to_thread(repos_update.update, self.root, sid, to, False, force_busy, commit, hooks)
                result = res.to_dict()
            except Exception as e:  # noqa: BLE001
                log.exception("updating %s", sid)
                result = {"id": sid, "ok": False, "message": str(e), "refused": []}
            self.update_job.update(running=False, result=result)
            self.hub.bus.publish({"type": "repos", "id": sid, "done": True, "ok": result.get("ok")})
            await self.hub.activity.add(f"{sid}: {result.get('message')}", service=sid,
                                        level="info" if result.get("ok") else "warn", route="#/settings/services/repositories")
            await self.refresh()

        self.update_job["task"] = asyncio.create_task(go())
        return self.job_view()

    def job_view(self) -> dict[str, Any] | None:
        if not self.update_job:
            return None
        return {k: v for k, v in self.update_job.items() if k != "task"}

    async def pin(self, sid: str) -> dict[str, Any]:
        res = await asyncio.to_thread(repos_update.pin, self.root, sid)
        await self.refresh()
        return res.to_dict()
