"""Hub events: the bus behind `GET /api/events`, the activity log and alerts.

Events are plain dicts shaped like the UI's `HubEvent` (brief §6.4), e.g.
`{"type": "activity", "item": {...}}`. Each SSE subscriber has its own
bounded queue; when a slow one fills it, its queued events are dropped
and replaced by `{"type": "resync"}`, so the UI refetches instead of
drifting.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections import deque
from collections.abc import AsyncIterator
from typing import Any, Literal

from utils.db import Database

HubEvent = dict[str, Any]
Level = Literal["info", "warn", "error"]

QUEUE_SIZE = 1000
RESYNC: HubEvent = {"type": "resync"}
SSE_RETRY_MS = 3000
SSE_PING_S = 15.0
ACTIVITY_KEEP = 500
ACTIVITY_MAX_AGE_S = 30 * 86400


class Subscription:
    def __init__(self, bus: EventBus, size: int) -> None:
        self._bus = bus
        self.queue: asyncio.Queue[HubEvent] = asyncio.Queue(size)

    def put(self, event: HubEvent) -> None:
        q = self.queue
        if q.full():
            # The UI refetches on resync, so everything still queued is stale.
            while not q.empty():
                q.get_nowait()
            q.put_nowait(RESYNC)
        q.put_nowait(event)

    async def get(self) -> HubEvent:
        return await self.queue.get()

    def close(self) -> None:
        self._bus._subs.discard(self)

    def __aiter__(self) -> AsyncIterator[HubEvent]:
        return self._iter()

    async def _iter(self) -> AsyncIterator[HubEvent]:
        while True:
            yield await self.get()


class EventBus:
    def __init__(self, queue_size: int = QUEUE_SIZE) -> None:
        self._subs: set[Subscription] = set()
        self._size = queue_size

    def subscribe(self) -> Subscription:
        sub = Subscription(self, self._size)
        self._subs.add(sub)
        return sub

    def publish(self, event: HubEvent) -> None:
        """Fan `event` out to every subscriber. Never blocks."""
        for sub in list(self._subs):
            sub.put(event)

    @property
    def subscribers(self) -> int:
        return len(self._subs)


class ActivityLog:
    """Persisted in `activity`; the last 500 are kept in memory for the UI."""

    def __init__(self, db: Database, bus: EventBus) -> None:
        self._db = db
        self._bus = bus
        self._recent: deque[dict[str, Any]] = deque(maxlen=ACTIVITY_KEEP)

    async def load(self) -> None:
        await self.prune()
        rows = await self._db.fetchall(
            "SELECT * FROM activity ORDER BY id DESC LIMIT ?", (ACTIVITY_KEEP,)
        )
        self._recent.clear()
        self._recent.extend(_activity(r) for r in reversed(rows))

    async def add(
        self, text: str, service: str | None = None, level: Level = "info", route: str | None = None
    ) -> dict[str, Any]:
        ts = time.time()
        rid = await self._db.execute(
            "INSERT INTO activity (ts, service, level, text, route) VALUES (?, ?, ?, ?, ?)",
            (ts, service, level, text, route),
        )
        item = _activity({"id": rid, "ts": ts, "service": service, "level": level, "text": text, "route": route})
        self._recent.append(item)
        self._bus.publish({"type": "activity", "item": item})
        return item

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        """Newest first."""
        return list(reversed(self._recent))[:limit]

    async def prune(self, now: float | None = None) -> int:
        cutoff = (now or time.time()) - ACTIVITY_MAX_AGE_S
        n = await self._db.execute("DELETE FROM activity WHERE ts < ?", (cutoff,))
        kept = [a for a in self._recent if a["ts"] >= cutoff]
        self._recent.clear()
        self._recent.extend(kept)
        return n


def _activity(row: dict[str, Any]) -> dict[str, Any]:
    item = {k: row[k] for k in ("ts", "service", "level", "text")}
    item["id"] = str(row["id"])
    if row.get("route"):
        item["route"] = row["route"]
    return item


class Alerts:
    """A keyed set of current alerts (brief `Alert`). Changes are published."""

    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self._alerts: dict[str, dict[str, Any]] = {}

    def set(
        self,
        id: str,
        level: Literal["warn", "error"],
        text: str,
        service: str | None = None,
        action: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        alert: dict[str, Any] = {"id": id, "level": level, "text": text}
        if service:
            alert["service"] = service
        if action:
            alert["action"] = action
        if self._alerts.get(id) != alert:
            self._alerts[id] = alert
            self._bus.publish({"type": "alert", "alert": alert})
        return alert

    def clear(self, id: str) -> bool:
        if self._alerts.pop(id, None) is None:
            return False
        self._bus.publish({"type": "alert_cleared", "id": id})
        return True

    def list(self) -> list[dict[str, Any]]:
        return list(self._alerts.values())


def sse_frame(event: HubEvent) -> str:
    return f"data: {json.dumps(event, separators=(',', ':'))}\n\n"


async def sse_stream(bus: EventBus, ping_s: float = SSE_PING_S) -> AsyncIterator[str]:
    """`retry:` first, then one `data:` frame per event and a `: ping` comment when idle."""
    sub = bus.subscribe()
    try:
        yield f"retry: {SSE_RETRY_MS}\n\n"
        while True:
            try:
                event = await asyncio.wait_for(sub.get(), ping_s)
            except TimeoutError:
                yield ": ping\n\n"
                continue
            yield sse_frame(event)
    finally:
        sub.close()
