"""When a task before a calendar event runs (plan calendar 6.2): `{kind: "event", item, before_min}`.

The calendar mod answers the item's occurrences (`GET /api/s/calendar/v1/items/{id}/next?after=`). The next run is
the first occurrence that hasn't ended and has no run yet, `before_min` minutes before it starts; one missed while
the agent was down runs late while its event hasn't ended. Answers are kept `TTL_S` seconds. An item that's gone
(404) turns the task off; the calendar being down leaves it waiting.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any

log = logging.getLogger("agent.tasks")
TTL_S = 60
LOOKBACK_S = 86400


class EventGone(Exception):
    pass


class EventDue:
    def __init__(self, hub: Any, tasks: Any, clock: Any = time.time) -> None:
        self.hub, self.k, self.clock = hub, tasks, clock
        self.cache: dict[str, tuple[float, tuple[float, str, str] | None]] = {}

    def forget(self, tid: str | None = None) -> None:
        if tid is None:
            self.cache.clear()
        else:
            self.cache.pop(tid, None)

    async def next(self, task: dict[str, Any], now: float) -> tuple[float, str, str] | None:
        """(due, occurrence, title) of the task's next run, or None (no occurrence ahead, or the calendar is down)."""
        hit = self.cache.get(task["id"])
        if hit and now - hit[0] < TTL_S:
            return hit[1]
        s = task["schedule"]
        before = int(s.get("before_min") or 0) * 60
        done = self.k.occurrences_run(task["id"])
        after = now - LOOKBACK_S
        out = None
        try:
            for _ in range(8):
                r = await self.hub.calendar_next(str(s["item"]), datetime.fromtimestamp(after).astimezone().isoformat(timespec="seconds"))
                o = (r or {}).get("next")
                if not o:
                    break
                end = o.get("end_ts") if o.get("end_ts") is not None else o["ts"]
                if o["occurrence"] in done or end <= now:
                    after = o["ts"] + 60
                    continue
                out = (o["ts"] - before, o["occurrence"], o.get("title") or "")
                break
        except Exception as e:  # noqa: BLE001
            status = getattr(e, "status", None) or getattr(getattr(e, "response", None), "status_code", None)
            if status == 404 and getattr(e, "code", "") != "service_not_running":
                raise EventGone(str(s["item"])) from None
            log.info("the calendar didn't answer for task %s: %s", task["id"], e)
            return hit[1] if hit else None
        self.cache[task["id"]] = (now, out)
        return out
