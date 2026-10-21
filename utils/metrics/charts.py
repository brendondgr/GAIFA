"""Chart data besides time series (brief §11.7): the timeline, and output, activity and job stats.

Days and hours are the hub's local time, like the charts' axes.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from utils.db import Database

OUTPUT_KINDS = ("audio", "image", "video", "model3d", "text", "archive", "other")


def _clip(a: float, b: float | None, frm: float, to: float) -> tuple[float, float] | None:
    b = to if b is None else b
    a, b = max(a, frm), min(b, to)
    return (a, b) if b > a else None


async def timeline(db: Database, services: list[str], frm: float, to: float) -> dict[str, Any]:
    lanes = []
    for sid in services:
        states = [{"from": c[0], "to": c[1], "state": r["state"]}
                  for r in await db.fetchall(
                      "SELECT state, from_ts, to_ts FROM service_states WHERE service = ? AND from_ts < ? "
                      "AND (to_ts IS NULL OR to_ts > ?) ORDER BY from_ts", (sid, to, frm))
                  if (c := _clip(r["from_ts"], r["to_ts"], frm, to))]
        loaded = [{"from": c[0], "to": c[1]}
                  for r in await db.fetchall(
                      "SELECT from_ts, to_ts FROM load_intervals WHERE service = ? AND from_ts < ? "
                      "AND (to_ts IS NULL OR to_ts > ?) ORDER BY from_ts", (sid, to, frm))
                  if (c := _clip(r["from_ts"], r["to_ts"], frm, to))]
        jobs = [{"id": r["job_id"], "label": r["label"], "from": max(r["start_ts"], frm),
                 "to": None if r["end_ts"] is None else min(r["end_ts"], to), "state": r["state"]}
                for r in await db.fetchall(
                    "SELECT job_id, label, state, start_ts, end_ts FROM job_history WHERE service = ? AND start_ts < ? "
                    "AND (end_ts IS NULL OR end_ts >= ?) ORDER BY start_ts", (sid, to, frm))]
        outputs = [{"ts": r["created_ts"], "id": r["id"], "kind": r["kind"]}
                   for r in await db.fetchall(
                       "SELECT id, kind, created_ts FROM outputs WHERE service = ? AND created_ts >= ? AND created_ts < ? "
                       "ORDER BY created_ts", (sid, frm, to))]
        events = [{"ts": r["ts"], "level": r["level"], "text": r["text"]}
                  for r in await db.fetchall(
                      "SELECT ts, level, text FROM activity WHERE service = ? AND level IN ('warn', 'error') "
                      "AND ts >= ? AND ts < ? ORDER BY ts", (sid, frm, to))]
        lanes.append({"service": sid, "states": states, "loaded": loaded, "jobs": jobs, "outputs": outputs, "events": events})
    return {"from": frm, "to": to, "lanes": lanes}


def _days(frm: float, to: float) -> list[str]:
    d, end = date.fromtimestamp(frm), date.fromtimestamp(to)
    out = []
    while d <= end:
        out.append(d.isoformat())
        d += timedelta(days=1)
    return out


async def output_stats(db: Database, frm: float, to: float, by: str) -> dict[str, Any]:
    rows = await db.fetchall("SELECT service, kind, size_bytes, created_ts FROM outputs WHERE created_ts >= ? AND created_ts < ? "
                             "AND hidden = 0", (frm, to))     # hidden outputs (saved web pages) aren't counted, as on the Outputs page
    buckets: dict[str, dict[str, Any]] = {}
    if by == "day":
        for d in _days(frm, to):
            buckets[d] = {"key": d, "count": 0, "size_bytes": 0, "by_kind": {}}
    for r in rows:
        key = {"day": lambda: date.fromtimestamp(r["created_ts"]).isoformat(), "service": lambda: r["service"],
               "kind": lambda: r["kind"]}[by]()
        b = buckets.setdefault(key, {"key": key, "count": 0, "size_bytes": 0, "by_kind": {}})
        b["count"] += 1
        b["size_bytes"] += r["size_bytes"] or 0
        b["by_kind"][r["kind"]] = b["by_kind"].get(r["kind"], 0) + 1
    out = list(buckets.values())
    if by != "day":
        out.sort(key=lambda b: (-b["count"], b["key"]))
    return {"buckets": out}


async def activity_stats(db: Database, frm: float, to: float) -> dict[str, Any]:
    """Every day × hour cell in the range (zeros included), for the heatmap."""
    cells: dict[tuple[str, int], dict[str, Any]] = {}
    for d in _days(frm, to):
        for h in range(24):
            cells[(d, h)] = {"day": d, "hour": h, "count": 0, "errors": 0}
    for r in await db.fetchall("SELECT ts, level FROM activity WHERE ts >= ? AND ts < ?", (frm, to)):
        t = datetime.fromtimestamp(r["ts"])
        c = cells.get((t.date().isoformat(), t.hour))
        if c is None:
            continue
        c["count"] += 1
        c["errors"] += r["level"] == "error"
    return {"cells": list(cells.values())}


def _pct(xs: list[float], p: float) -> float:
    """Nearest-rank percentile."""
    if not xs:
        return 0.0
    xs = sorted(xs)
    k = max(0, min(len(xs) - 1, int(-(-p * len(xs) // 1)) - 1))
    return round(xs[k], 3)


async def job_stats(db: Database, frm: float, to: float, services: list[str] | None = None) -> dict[str, Any]:
    """Jobs started in the range, per mod: count, failed, and p50/p90/max duration of the finished ones."""
    rows = await db.fetchall("SELECT service, state, start_ts, end_ts FROM job_history WHERE start_ts >= ? AND start_ts < ?", (frm, to))
    per: dict[str, dict[str, Any]] = defaultdict(lambda: {"count": 0, "failed": 0, "durations": []})
    for r in rows:
        p = per[r["service"]]
        p["count"] += 1
        p["failed"] += r["state"] == "failed"
        if r["end_ts"] is not None and r["state"] == "done":
            p["durations"].append(max(0.0, r["end_ts"] - r["start_ts"]))
    order = list(services or []) + sorted(s for s in per if s not in (services or []))
    out = []
    for sid in order:
        if sid not in per:
            continue
        p = per[sid]
        ds = p["durations"]
        out.append({"service": sid, "count": p["count"], "failed": p["failed"], "p50_s": _pct(ds, 0.5),
                    "p90_s": _pct(ds, 0.9), "max_s": round(max(ds), 3) if ds else 0.0})
    return {"by_service": out}
