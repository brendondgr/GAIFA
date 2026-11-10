"""What you did each day (plan calendar 8.1), for the Calendar's History layer: per local day, the chats with a
message of yours that day, from their first to their last event, with how many turns; a scheduled task's runs are
flagged. Archived chats count too. At most 500 rows."""

from __future__ import annotations

import json
import time
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request

MAX_ROWS = 500


def history(store: Any, frm: float, to: float) -> list[dict[str, Any]]:
    with store._lock:
        rows = store._c.execute(
            "SELECT e.thread_id, e.ts, e.type, t.title, t.settings FROM events e JOIN threads t ON t.id = e.thread_id "
            "WHERE e.ts >= ? AND e.ts < ? ORDER BY e.ts", (frm, to)).fetchall()
    days: dict[tuple[str, str], dict[str, Any]] = {}
    for tid, ts, kind, title, settings in rows:
        day = time.strftime("%Y-%m-%d", time.localtime(ts))
        d = days.get((tid, day))
        if d is None:
            st = json.loads(settings or "{}")
            d = days[(tid, day)] = {"thread_id": tid, "title": title or "Untitled chat", "day": day, "first": ts, "last": ts, "turns": 0,
                                    "project": st.get("project"), "task": st.get("task")}
        d["last"] = ts
        if kind == "user":
            d["turns"] += 1
    out = [d for d in days.values() if d["turns"]]
    out.sort(key=lambda d: d["first"])
    return out[:MAX_ROWS]


def add_routes(app: FastAPI) -> None:
    @app.get("/v1/history", summary="The chats you had each day between from and to (unix seconds), for the Calendar (calendar 8.1)")
    def get_history(request: Request, from_: float = Query(..., alias="from"), to: float = Query(...)) -> dict:
        if to <= from_ or to - from_ > 62 * 86400:
            raise HTTPException(422, "the range is from < to, up to 62 days")
        return {"chats": history(request.app.state.agent.store, from_, to)}
