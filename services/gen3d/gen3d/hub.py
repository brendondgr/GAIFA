"""Routes for GAIFA (architecture §4.6 and brief §11.7): the status GAIFA polls, and the
"Job time per stage" dashboard widget. Both work without GAIFA too."""

from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException, Query, Request

from . import prefs
from .live import live_of
from .options import STAGE_ORDER

router = APIRouter()
STATE = {"canceled": "cancelled"}       # GAIFA's job states spell it the British way
RECENT_S = 120                           # finished jobs stay in the status this long
WIDGET_RANGES = {"7d": 7, "30d": 30}


def progress(job: dict) -> float | None:
    """0-1 over the job's stages: finished stages count whole, the running one by its steps."""
    stages = job.get("stages") or {}
    if not stages:
        return None
    total = 0.0
    for v in stages.values():
        st = v.get("state")
        if st in ("done", "skipped", "failed", "canceled"):
            total += 1
        elif st == "running" and v.get("total"):
            total += min(1.0, (v.get("step") or 0) / v["total"]) * 0.95
    return round(total / len(stages), 3)


def _job(job: dict, runner=None, sched: dict | None = None) -> dict:
    out = {"id": job["id"], "label": (job.get("title") or job["id"])[:80], "progress": progress(job),
           "state": STATE.get(job["status"], job["status"]), "route": f"#/s/gen3d/jobs?id={job['id']}"}
    if runner is not None:                              # plan 45.3: previews wherever GAIFA shows jobs
        lv = live_of(job, (sched or {}).get(job["id"]), runner.store.job_dir(job["id"]))
        if lv:
            out["live"] = lv
    w = runner.gpu_wait.get(job["id"]) if runner is not None and job["status"] == "queued" else None
    if w is not None:                                   # waiting for the GPU slot (plan 31.3)
        out.update(stage="waiting_gpu", ahead=w["ahead"], eta_s=w["eta_s"])
    return out


@router.get("/v1/status")
def status(request: Request):
    """{loaded, busy, idle_s, stats, jobs}: loaded = the worker is up with models in memory."""
    runner, store = request.app.state.runner, request.app.state.store
    w = runner.worker
    now = time.time()
    active = store.list_jobs(status="queued,running", limit=50)
    recent = [j for j in store.list_jobs(status="done,failed,canceled", limit=10)
              if j.get("finished") and now - j["finished"] < RECENT_S]
    done = store.list_jobs(status="done", limit=20)
    secs = [j["finished"] - j["started"] for j in done if j.get("started") and j.get("finished")]
    total = store.count("done")
    sched = runner.schedule() if active else {}
    return {
        "loaded": bool(w.up and w.loaded),
        "busy": runner.current is not None,
        "idle_s": round(time.monotonic() - runner.last_activity, 1) if w.up and not runner.current else None,
        "worker": w.status(),
        "stats": [
            {"label": "Jobs", "value": total},
            {"label": "Queue", "value": sum(1 for j in active if j["status"] == "queued")},
            {"label": "Avg time", "value": round(sum(secs) / len(secs)) if secs else None, "unit": "s"},
            {"label": "Previews", "value": prefs.preview_device().upper(), "hint": "where Blender draws preview renders"},
        ],
        "jobs": [_job(j, runner, sched) for j in sorted(active, key=lambda j: j["created"])] + [_job(j) for j in recent],
    }


@router.get("/v1/hub/widgets/stages")
def stages_widget(request: Request, range: str = Query("7d", description="7d or 30d")):
    """Seconds per stage for the jobs finished in the range (oldest first, at most 30), as stacked bars."""
    if range not in WIDGET_RANGES:
        raise HTTPException(422, f"range must be one of {sorted(WIDGET_RANGES)}")
    since = time.time() - WIDGET_RANGES[range] * 86400
    jobs = [j for j in request.app.state.store.list_jobs(status="done", limit=500) if (j.get("finished") or 0) >= since]
    jobs = sorted(jobs, key=lambda j: j["finished"])[-30:]
    series = [{"name": s, "values": [round((j["stages"].get(s) or {}).get("seconds") or 0, 1) or None for j in jobs]}
              for s in STAGE_ORDER]
    # Short labels (finish time); a job's title is in `rows` for the table view.
    return {"unit": "seconds", "categories": [time.strftime("%m-%d %H:%M", time.localtime(j["finished"])) for j in jobs],
            "rows": [{"job": j.get("title") or j["id"], **{s: (j["stages"].get(s) or {}).get("seconds") or 0 for s in STAGE_ORDER}} for j in jobs],
            "series": [s for s in series if any(v for v in s["values"])]}

