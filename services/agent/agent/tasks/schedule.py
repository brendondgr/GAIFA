"""When scheduled tasks run (plan scheduled-tasks 2.3): a check every `CHECK_S` seconds.

- **Due:** each task on whose `next_due` has passed starts a run (`Runner.start`), and `next_due` moves to the next time
  after now.
- **Missed:** a task due more than `GRACE_S` ago (GAIFA was off, or the machine asleep) runs once, for the latest due
  time, with `late` = how many due times passed; the older ones aren't run.
- **The queue:** each check also launches queued runs while slots are free (`Runner.drain`).
- **Upkeep:** once a day, run chats older than their task's `keep_days` are archived (never deleted).
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from . import when

log = logging.getLogger("agent.tasks")
CHECK_S = 30
GRACE_S = 120


def latest_due(schedule: dict[str, Any], due: float, now: float) -> tuple[float, int]:
    """The last due time at or before `now`, starting from `due`, and how many due times that makes."""
    last, n = due, 1
    while n < when.MISSED_MAX:
        nxt = when.next_after(schedule, last)
        if nxt > now:
            break
        last, n = nxt, n + 1
    return last, n


class TaskSchedule:
    def __init__(self, agent: Any, runner: Any, clock: Any = time.time, grace_s: float = GRACE_S) -> None:
        self.agent, self.runner, self.clock, self.grace_s = agent, runner, clock, grace_s
        self.k = agent.scheduled
        self.last_upkeep: str | None = None

    async def tick(self) -> list[dict[str, Any]]:
        """One check; returns the runs it started (or skipped)."""
        now = self.clock()
        started = []
        for t in self.k.due(now):
            due, late = t["next_due"], 0
            if now - due > self.grace_s:
                due, late = latest_due(t["schedule"], due, now)
            self.k.update(t["id"], next_due=when.next_after(t["schedule"], now))
            try:
                started.append(await self.runner.start(t, "late" if late else "schedule", due=due, late=late))
            except Exception:  # noqa: BLE001: one task never stops the others
                log.exception("starting task %s", t["id"])
        await self.runner.drain()
        self.upkeep(now)
        return started

    def upkeep(self, now: float) -> int:
        day = time.strftime("%Y-%m-%d", time.localtime(now))
        if self.last_upkeep == day:
            return 0
        self.last_upkeep = day
        n = 0
        for tid in self.k.old_run_chats(now):
            self.agent.store.update_thread(tid, archived=True)
            n += 1
        if n:
            log.info("archived %d old scheduled-run chats", n)
        return n

    async def run_forever(self, stop: asyncio.Event, every: float = CHECK_S) -> None:
        while not stop.is_set():
            try:
                await self.tick()
            except Exception:  # noqa: BLE001
                log.exception("the task scheduler")
            try:
                await asyncio.wait_for(stop.wait(), timeout=every)
            except asyncio.TimeoutError:
                pass
