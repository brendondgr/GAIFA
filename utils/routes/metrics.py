"""The `metrics` area: chart data (brief §11.7, architecture §13).

`GET /api/metrics` picks the table from the range (≤ 6 h raw samples, ≤ 7 d minute rollups,
longer hour rollups) and answers on an even `t` axis with `null` for gaps.
"""

from __future__ import annotations

import time
from typing import Any, Literal

from fastapi import APIRouter, Query, Request

from utils.api_models import ActivityStats, JobStats, Metrics, OutputStats, SeriesInfo, Timeline
from utils.metrics import charts
from utils.metrics.store import MetricsError, parse_range, pick_step

router = APIRouter(tags=["metrics"])


def _hub(request: Request) -> Any:
    return request.app.state.hub


def _range(value: str | None, default: str) -> tuple[str, int]:
    return parse_range(value, default)  # MetricsError → 422 invalid_request (server.py)


def _list(value: str | None) -> list[str]:
    return [x.strip() for x in (value or "").split(",") if x.strip()]


@router.get("/api/metrics", summary="Time series on an even t axis (series may end in .* for a family)", response_model=Metrics)
async def get_metrics(request: Request,
                      series: str = Query(..., description="Comma-separated names, e.g. mem.used,mem.svc.*"),
                      range: str = Query("1h", description="1h, 6h, 24h, 7d, 30d or <n>m|h|d"),
                      step: int | None = Query(None, ge=1, description="Bucket size in seconds (rounded to the table's resolution)")) -> dict[str, Any]:
    name, seconds = _range(range, "1h")
    names = _list(series)
    if not names:
        raise MetricsError("series: name at least one series")
    step_s = pick_step(seconds, step)
    store = _hub(request).metrics.store
    to = time.time()
    frm = to - seconds
    t, values = await store.query(await store.expand(names, frm), frm, to, step_s)
    return {"range": name, "step_s": step_s, "t": t, "series": values}


@router.get("/api/metrics/series", summary="Every recorded series with its label and unit", response_model=list[SeriesInfo], response_model_exclude_none=True)
async def list_series(request: Request) -> list[dict[str, Any]]:
    return [s.as_dict() for s in await _hub(request).metrics.store.series()]


@router.get("/api/timeline", summary="One lane per mod: states, loaded spans, jobs, outputs, warnings", response_model=Timeline)
async def get_timeline(request: Request, range: str = Query("24h"), services: str | None = Query(None, description="Comma-separated mod ids (default: all)")) -> dict[str, Any]:
    _, seconds = _range(range, "24h")
    hub = _hub(request)
    ids = _list(services) or [s.id for s in hub.services.list()]
    to = time.time()
    return await charts.timeline(hub.db, ids, to - seconds, to)


@router.get("/api/outputs/stats", summary="Outputs per day, mod or kind", response_model=OutputStats)
async def output_stats(request: Request, range: str = Query("30d"), by: Literal["day", "service", "kind"] = "day") -> dict[str, Any]:
    _, seconds = _range(range, "30d")
    to = time.time()
    return await charts.output_stats(_hub(request).db, to - seconds, to, by)


@router.get("/api/activity/stats", summary="Activity per local day and hour (every cell, zeros included)", response_model=ActivityStats)
async def activity_stats(request: Request, range: str = Query("14d")) -> dict[str, Any]:
    _, seconds = _range(range, "14d")
    to = time.time()
    return await charts.activity_stats(_hub(request).db, to - seconds, to)


@router.get("/api/jobs/stats", summary="Jobs per mod: count, failed, p50/p90/max duration", response_model=JobStats)
async def job_stats(request: Request, range: str = Query("7d")) -> dict[str, Any]:
    _, seconds = _range(range, "7d")
    hub = _hub(request)
    to = time.time()
    return await charts.job_stats(hub.db, to - seconds, to, [s.id for s in hub.services.list()])
