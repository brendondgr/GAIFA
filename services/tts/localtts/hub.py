"""Routes for GAIFA (architecture §4.6 and brief §11.7): the status GAIFA polls, and the
"Clips per day" dashboard widget. Both work without GAIFA too."""

from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException, Query

from . import outputs, voices
from .config import settings
from .engines import ENGINES, WAITING
from .jobs import JOBS

router = APIRouter()
WIDGET_RANGES = {"7d": 7, "30d": 30}


@router.get("/v1/status")
def status():
    """{loaded, busy, idle_s, stats}: loaded = any engine worker up; busy = an engine is generating."""
    alive = [e for e in ENGINES.values() if e.alive]
    now = time.monotonic()
    return {
        "loaded": bool(alive),
        "busy": any(e._lock.locked() or e.state == "loading" for e in ENGINES.values()) or bool(WAITING),
        "idle_s": round(min(now - e.last_used for e in alive), 1) if alive else None,
        "engines": {n: e.status() for n, e in ENGINES.items()},
        "stats": [
            {"label": "Voices", "value": len(voices.all_voices())},
            {"label": "Engines installed", "value": sum(1 for e in ENGINES.values() if e.python.exists())},
            {"label": "Clips today", "value": outputs.clips_today(settings.outputs_dir), "reset": "daily"},
        ],
        # Requests waiting for GAIFA's GPU slot (plan 31.3): stage waiting_gpu, with what runs before them.
        "jobs": [{**j, "route": "#/s/tts"} for j in list(WAITING.values())] + _speech_jobs(),
    }


def _speech_jobs() -> list[dict]:
    """Speech jobs (plan 45.4) making audio now, with their live progress; a waiting one is listed by WAITING."""
    out = []
    for jid, j in list(JOBS.jobs.items()):
        if j["state"] not in ("queued", "running") or jid in WAITING:
            continue
        p = JOBS.public(j)
        out.append({"id": f"speech-{jid}", "label": p["label"], "progress": p["progress"], "state": p["state"],
                    "route": "#/s/tts", **({"live": p["live"]} if p.get("live") else {})})
    return out


@router.get("/v1/hub/widgets/clips")
def clips_widget(range: str = Query("7d", description="7d or 30d")):
    """Clips per day by voice, as GAIFA WidgetData (stacked bars)."""
    if range not in WIDGET_RANGES:
        raise HTTPException(422, f"range must be one of {sorted(WIDGET_RANGES)}")
    labels, counts = outputs.clips_by_day(settings.outputs_dir, WIDGET_RANGES[range])
    order = sorted(counts, key=lambda v: -sum(counts[v]))
    return {"unit": "count", "categories": [d[5:] for d in labels],
            "series": [{"name": v, "values": counts[v]} for v in order]}
