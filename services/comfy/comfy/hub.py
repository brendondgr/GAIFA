"""Routes for AIHub (architecture §4.6): the status AIHub polls."""

from __future__ import annotations

import time

from fastapi import APIRouter, Request

router = APIRouter()


def _queue_jobs(ctl) -> list[dict]:
    """ComfyUI's own queue, for prompts AIHub didn't queue (from ComfyUI's page)."""
    out = []
    for state, entries in (("running", ctl.running), ("queued", ctl.pending)):
        for e in entries:
            pid = e[1] if len(e) > 1 else str(e)
            out.append({"id": f"comfy-{pid}", "label": "ComfyUI prompt", "progress": None, "state": state,
                        "route": "#/s/comfy"})
    return out


@router.get("/v1/status", summary="Load state, queue and stats for AIHub")
def status(request: Request) -> dict:
    st = request.app.state
    ctl = st.control
    packs = getattr(st, "packs", None)
    ready = packs.count_ready() if packs else 0
    drafts = packs.count_drafts() if packs else 0
    return {
        "loaded": ctl.up,
        "busy": ctl.busy or ctl.state != "idle",
        "idle_s": round(time.monotonic() - ctl.last_activity, 1) if ctl.up and not ctl.busy else None,
        "stats": [
            {"label": "Workflows", "value": ready},
            {"label": "Drafts", "value": drafts},
            {"label": "Queue", "value": len(ctl.pending) + len(ctl.running)},
        ],
        "jobs": _queue_jobs(ctl),
    }
