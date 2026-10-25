"""``GET /api/status`` for GAIFA (its architecture §4.6): loaded/busy, KPIs for the Overview
tile, and jobs (instances starting, downloads running) for the header. Works without GAIFA too."""

from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter, Request

from lcpp.daemon.app import state

router = APIRouter(prefix="/api", tags=["gaifa"])
RECENT_S = 120  # finished downloads stay in the status this long


def _download_job(d: dict) -> dict:
    total = d.get("bytes_total") or 0
    st = {"queued": "queued", "downloading": "running", "done": "done", "failed": "failed", "cancelled": "cancelled"}
    return {"id": f"dl-{d['id']}", "label": f"Download {d.get('model_id') or d['label']}",
            "progress": round(d["bytes_done"] / total, 3) if total else None,
            "state": st.get(d["state"], "running"), "route": "#/s/lcpp/catalog"}


@router.get("/status")
async def status(request: Request):
    st = state(request)
    sup, cat = st.supervisor, st.catalog
    insts = list(sup.instances.values())
    on_disk = await asyncio.to_thread(lambda: sum(cat.size_bytes(m) for m in cat.models.values()))
    now = time.time()
    downloads = [d for d in st.downloads.list()
                 if d["state"] in ("queued", "downloading") or (d.get("finished_ts") and now - d["finished_ts"] < RECENT_S)]
    jobs = [{"id": f"inst-{i.name}", "label": f"Starting {i.name}", "progress": None, "state": "running",
             "route": "#/s/lcpp/instances"} for i in insts if i.state == "starting"]
    return {
        "loaded": any(i.state == "ready" for i in insts),
        "busy": any(i.state == "starting" for i in insts) or any(d["state"] == "downloading" for d in downloads),
        "stats": [
            {"label": "Running", "value": sum(1 for i in insts if i.state in ("starting", "ready"))},
            {"label": "Catalog", "value": len(cat.models)},
            {"label": "On disk", "value": round(on_disk / 1e9, 1), "unit": "GB"},
        ],
        "jobs": jobs + [_download_job(d) for d in downloads],
    }
