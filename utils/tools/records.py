"""Tool records (plan 21.1): retention of eval rows, and per-tool usage for the Learning page.

Real calls, approvals and refusals are kept; rows a dry run made (`origin.dry_run`, the agent eval)
go after `DRY_RUN_KEEP_S`, from the metrics recorder's hourly maintenance.
"""

from __future__ import annotations

import time
from typing import Any

DRY_RUN_KEEP_S = 30 * 86400
DRY = "json_extract(origin, '$.dry_run') IS NOT NULL AND json_extract(origin, '$.dry_run') != 0"


async def prune_dry_runs(db: Any, now: float | None = None) -> int:
    cutoff = (now or time.time()) - DRY_RUN_KEEP_S
    n = 0
    for table in ("tool_calls", "approvals", "tool_refusals"):
        n += await db.execute(f"DELETE FROM {table} WHERE created_ts < ? AND {DRY}", (cutoff,)) or 0
    return n


async def usage(db: Any, since: float) -> list[dict[str, Any]]:
    """Per tool since `since`, real calls only: calls, errors, refusals, cards, cards the user changed, denials."""
    out: dict[str, dict[str, Any]] = {}

    def row(tool: str) -> dict[str, Any]:
        return out.setdefault(tool, {"tool": tool, "calls": 0, "errors": 0, "refused": 0, "cards": 0, "edited": 0, "denied": 0,
                                     "mean_ms": None})
    for r in await db.fetchall(f"SELECT tool, count(*) n, sum(state = 'error') e, avg(duration_ms) ms FROM tool_calls "
                               f"WHERE created_ts >= ? AND NOT ({DRY}) GROUP BY tool", (since,)):
        x = row(r["tool"])
        x.update(calls=r["n"], errors=r["e"] or 0, mean_ms=round(r["ms"]) if r["ms"] is not None else None)
    for r in await db.fetchall(f"SELECT tool, count(*) n FROM tool_refusals WHERE created_ts >= ? AND NOT ({DRY}) GROUP BY tool", (since,)):
        row(r["tool"])["refused"] = r["n"]
    for r in await db.fetchall(f"SELECT tool, count(*) n, sum(state = 'denied') d, "
                               f"sum(edited IS NOT NULL AND edited != '[]') ed FROM approvals WHERE created_ts >= ? AND NOT ({DRY}) GROUP BY tool",
                               (since,)):
        row(r["tool"]).update(cards=r["n"], denied=r["d"] or 0, edited=r["ed"] or 0)
    return sorted(out.values(), key=lambda x: -(x["calls"] + x["cards"]))
