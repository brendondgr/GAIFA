"""When the learner runs (plan 22.6): nightly at `[learning] nightly_at`, after `idle_min` minutes with
no chat (and only when something happened since the last run), and on Learn now. One run at a time;
nothing while learning is off (the hub's Settings → Learning, read on each check). A run pauses when
you start chatting (loop.Paused) and the next idle check picks it up again.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable

log = logging.getLogger("agent.learn")
CHECK_S = 60


class Schedule:
    def __init__(self, agent: Any, learner: Any, clock: Callable[[], float] = time.time) -> None:
        self.agent, self.learner, self.clock = agent, learner, clock
        self.task: asyncio.Task[Any] | None = None
        self.last_nightly: str | None = None              # the local date of the last nightly run
        self.last_run: float = 0.0

    async def settings(self) -> dict[str, Any]:
        try:
            return (await self.agent.hub.settings()).get("learning") or {}
        except Exception:  # noqa: BLE001: the hub may be restarting
            return {}

    def last_activity(self) -> float:
        rows = self.agent.store.events_by_type(["user"], 0)
        return rows[-1]["ts"] if rows else 0.0

    @property
    def busy(self) -> bool:
        return self.task is not None and not self.task.done()

    def start(self, why: str, domains: list[str] | None = None) -> bool:
        if self.busy:
            return False
        self.last_run = self.clock()
        self.task = asyncio.create_task(self.learner.run(domains, why=why))
        return True

    async def tick(self) -> str | None:
        """One check; returns why a run started, or None."""
        st = await self.settings()
        if not st.get("enabled", True) or self.busy:
            return None
        now = self.clock()
        lt = time.localtime(now)
        day = time.strftime("%Y-%m-%d", lt)
        hh, mm = (int(x) for x in str(st.get("nightly_at") or "03:00").split(":"))
        if self.last_nightly != day and (lt.tm_hour, lt.tm_min) >= (hh, mm):
            self.last_nightly = day
            asyncio.create_task(self._tidy())                                           # structured-memory 4.2
            if self.start("nightly"):
                return "nightly"
        active = self.last_activity()
        idle = now - max(active, 0)
        if active > self.last_run and idle >= int(st.get("idle_min") or 60) * 60 and not self.learner.user_active(now - 60):
            if self.start("idle"):
                return "idle"
        return None

    async def _tidy(self) -> None:
        from ..memory import profile, tidy
        try:
            await tidy.run(self.agent, int(profile.settings(self.agent.cfg.data).get("fade_days") or tidy.FADE_DAYS))
        except Exception:  # noqa: BLE001: tidying never stops the learner
            logging.getLogger("agent.memory.tidy").exception("tidying memory")

    async def run_forever(self, stop: asyncio.Event) -> None:
        # The first nightly is the next one: a hub started at noon doesn't run "last night's" round.
        lt = time.localtime(self.clock())
        st = await self.settings()
        hh, mm = (int(x) for x in str(st.get("nightly_at") or "03:00").split(":"))
        if (lt.tm_hour, lt.tm_min) >= (hh, mm):
            self.last_nightly = time.strftime("%Y-%m-%d", lt)
        self.last_run = self.last_activity()          # what happened before this start was learned from, or waits for a night
        while not stop.is_set():
            try:
                await self.tick()
            except Exception:  # noqa: BLE001
                log.exception("learner schedule")
            try:
                await asyncio.wait_for(stop.wait(), timeout=CHECK_S)
            except asyncio.TimeoutError:
                pass
        if self.task and not self.task.done():
            self.task.cancel()
