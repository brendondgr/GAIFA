"""Routes for AIHub (architecture §4.6): the status AIHub polls."""

from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException, Query, Request

router = APIRouter()
RANGES = {"24h": 1, "7d": 7, "30d": 30, "90d": 90}


def _queue_jobs(ctl, ours: set[str] = frozenset()) -> list[dict]:
    """ComfyUI's own queue, for prompts AIHub didn't queue (from ComfyUI's page)."""
    out = []
    for state, entries in (("running", ctl.running), ("queued", ctl.pending)):
        for e in entries:
            pid = e[1] if len(e) > 1 else str(e)
            if pid in ours:
                continue
            out.append({"id": f"comfy-{pid}", "label": "ComfyUI prompt", "progress": None, "state": state,
                        "route": "#/s/comfy"})
    return out


RECENT_S = 120
STATE = {"queued": "queued", "running": "running", "done": "done", "failed": "failed", "cancelled": "cancelled"}


def _run_jobs(db, runner=None) -> tuple[list[dict], set[str]]:
    now = time.time()
    rows = db.runs(states=("queued", "running"), limit=50)
    rows += [r for r in db.runs(states=("done", "failed", "cancelled"), limit=10) if now - (r.get("finished") or 0) < RECENT_S]
    jobs = []
    for r in sorted(rows, key=lambda r: r["created"]):
        r = runner.annotate(r) if runner is not None else r
        j = {"id": r["id"], "label": r["label"] or r["workflow"], "progress": r.get("progress"), "state": STATE[r["state"]],
             "route": f"#/s/comfy/run?job={r['id']}"}
        if r.get("stage"):                       # waiting for the GPU slot (plan 31.3)
            j.update(stage=r["stage"], ahead=r.get("ahead") or [], eta_s=r.get("eta_s"))
        jobs.append(j)
    return jobs, {r["prompt_id"] for r in rows if r.get("prompt_id")}


@router.get("/v1/status", summary="Load state, queue and stats for AIHub")
def status(request: Request) -> dict:
    st = request.app.state
    ctl = st.control
    packs = getattr(st, "packs", None)
    ready = packs.count_ready() if packs else 0
    drafts = packs.count_drafts() if packs else 0
    runs, ours = _run_jobs(st.db, getattr(st, "runner", None))
    today = time.mktime(time.localtime()[:3] + (0, 0, 0, 0, 0, -1))
    made = sum(len(r.get("outputs") or []) for r in st.db.runs(states=("done",), since=today, limit=1000))
    return {
        "loaded": ctl.up,
        "busy": ctl.busy or ctl.state != "idle",
        "idle_s": round(time.monotonic() - ctl.last_activity, 1) if ctl.up and not ctl.busy else None,
        "stats": [
            {"label": "Workflows", "value": ready},
            {"label": "Drafts", "value": drafts},
            {"label": "Queue", "value": len(ctl.pending) + len(ctl.running)},
            {"label": "Made today", "value": made, "reset": "daily"},
        ],
        "jobs": runs + _queue_jobs(ctl, ours),
    }


def _days(n: int) -> list[float]:
    """Local midnights for the last n days, oldest first."""
    t = time.localtime()
    today = time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1))
    return [today - 86400 * i for i in range(n - 1, -1, -1)]


@router.get("/v1/hub/widgets/made", summary="Images and videos made per day (dashboard widget)")
def made_widget(request: Request, range: str = Query("7d", description="7d or 30d")) -> dict:
    if range not in ("7d", "30d"):
        raise HTTPException(422, "range must be 7d or 30d")
    days = _days(RANGES[range])
    img, vid = [0] * len(days), [0] * len(days)
    for r in request.app.state.db.runs(states=("done",), since=days[0], limit=5000):
        i = max(0, min(len(days) - 1, int(((r.get("finished") or r["created"]) - days[0]) // 86400)))
        for o in r.get("outputs") or []:
            (vid if o.get("kind") == "video" else img)[i] += 1
    return {"unit": "files", "categories": [time.strftime("%m-%d", time.localtime(d)) for d in days],
            "series": [{"name": "Images", "values": img}, {"name": "Videos", "values": vid}]}


@router.get("/v1/stats", summary="Runs per workflow, their time and outcome, over a range")
def stats(request: Request, range: str = Query("30d", description="24h, 7d, 30d or 90d")) -> dict:
    if range not in RANGES:
        raise HTTPException(422, f"range must be one of {', '.join(RANGES)}")
    since = time.time() - RANGES[range] * 86400
    rows: dict[str, dict] = {}
    recent = []
    packs = request.app.state.library.packs
    for r in request.app.state.db.runs(since=since, limit=5000):
        w = rows.setdefault(r["workflow"], {"id": r["workflow"], "runs": 0, "done": 0, "failed": 0, "cancelled": 0, "secs": []})
        w["runs"] += 1
        if r["state"] in ("done", "failed", "cancelled"):
            w[r["state"]] += 1
        if r["state"] == "done" and r.get("started") and r.get("finished"):
            w["secs"].append(r["finished"] - r["started"])
            recent.append({"id": r["id"], "workflow": r["workflow"], "seconds": round(r["finished"] - r["started"], 1),
                           "finished": r["finished"], "peak_gb": r.get("peak_gb")})
    out = []
    for w in rows.values():
        secs = sorted(w.pop("secs"))
        p = packs.get(w["id"])
        out.append({**w, "name": p.name if p else w["id"], "avg_s": round(sum(secs) / len(secs), 1) if secs else None,
                    "p50_s": round(secs[len(secs) // 2], 1) if secs else None})
    return {"range": range, "workflows": sorted(out, key=lambda w: -w["runs"]),
            "recent": sorted(recent, key=lambda r: r["finished"])[-50:]}
