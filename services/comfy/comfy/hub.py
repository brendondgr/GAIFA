"""Routes for AIHub (architecture §4.6): the status AIHub polls."""

from __future__ import annotations

import time

from fastapi import APIRouter, Request

router = APIRouter()


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


def _run_jobs(db) -> tuple[list[dict], set[str]]:
    now = time.time()
    rows = db.runs(states=("queued", "running"), limit=50)
    rows += [r for r in db.runs(states=("done", "failed", "cancelled"), limit=10) if now - (r.get("finished") or 0) < RECENT_S]
    jobs = [{"id": r["id"], "label": r["label"] or r["workflow"], "progress": r.get("progress"), "state": STATE[r["state"]],
             "route": f"#/s/comfy/run?job={r['id']}"} for r in sorted(rows, key=lambda r: r["created"])]
    return jobs, {r["prompt_id"] for r in rows if r.get("prompt_id")}


@router.get("/v1/status", summary="Load state, queue and stats for AIHub")
def status(request: Request) -> dict:
    st = request.app.state
    ctl = st.control
    packs = getattr(st, "packs", None)
    ready = packs.count_ready() if packs else 0
    drafts = packs.count_drafts() if packs else 0
    runs, ours = _run_jobs(st.db)
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
