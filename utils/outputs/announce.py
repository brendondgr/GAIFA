"""Activity items for new outputs (plan 4.5), batched per mod.

A mod's new outputs are collected until it has been quiet for 2 s, or 10 s after the
first. Up to 5 become one item each ("Speech created "Good morning""); more become
a single item ("3D Generate created 8 outputs").
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("aihub.outputs")

QUIET_S = 2.0
WINDOW_S = 10.0
MAX_EACH = 5


@dataclass
class _Batch:
    start: float
    last: float
    items: list[dict[str, Any]] = field(default_factory=list)
    task: asyncio.Task[None] | None = None


class Announcer:
    def __init__(self, activity: Any, name_of: Callable[[str], str] = lambda s: s,
                 quiet_s: float = QUIET_S, window_s: float = WINDOW_S) -> None:
        self.activity = activity
        self.name_of = name_of
        self.quiet_s, self.window_s = quiet_s, window_s
        self._open: dict[str, _Batch] = {}

    def add(self, output: dict[str, Any]) -> None:
        now = asyncio.get_running_loop().time()
        svc = output["service"]
        b = self._open.get(svc)
        if b is None:
            b = self._open[svc] = _Batch(now, now)
            b.task = asyncio.create_task(self._close_later(svc, b), name=f"aihub-announce-{svc}")
        b.items.append(output)
        b.last = now

    async def _close_later(self, svc: str, b: _Batch) -> None:
        loop = asyncio.get_running_loop()
        while (wait := min(b.last + self.quiet_s, b.start + self.window_s) - loop.time()) > 0:
            await asyncio.sleep(wait)
        if self._open.get(svc) is b:
            del self._open[svc]
        await self._flush(svc, b.items)

    async def _flush(self, svc: str, items: list[dict[str, Any]]) -> None:
        try:
            name = self.name_of(svc)
            if len(items) <= MAX_EACH:
                for o in items:
                    await self.activity.add(f'{name} created "{o["title"]}"', svc, "info", f"#/outputs/{o['id']}")
            else:
                await self.activity.add(f"{name} created {len(items)} outputs", svc, "info", "#/outputs")
        except Exception:  # noqa: BLE001: the activity feed must not take the watcher down
            log.exception("output activity for %s", svc)

    async def close(self) -> None:
        """Write what is still waiting (shutdown)."""
        batches, self._open = list(self._open.items()), {}
        for svc, b in batches:
            if b.task:
                b.task.cancel()
                await asyncio.gather(b.task, return_exceptions=True)
            await self._flush(svc, b.items)
