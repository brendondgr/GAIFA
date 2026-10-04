"""__NAME__: an AIHub mod. Start from here, keep what you need.

AIHub runs this as `.venv/bin/python server.py` with these set (architecture §4.4):
    AIHUB_PORT       the port to listen on (127.0.0.1 only)
    AIHUB_OUTPUTS    where to write files the Outputs page should show
    AIHUB_URL        the hub, if this mod wants to call it
The hub only needs /health. Everything else is this mod's own API, reachable
through the hub at /api/s/__ID__/... and listed on its API tab.
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Query
from pydantic import BaseModel, Field

PORT = int(os.environ.get("AIHUB_PORT", "__PORT__"))
OUTPUTS = Path(os.environ.get("AIHUB_OUTPUTS", "outputs"))
PREFIX = os.environ.get("NOTE_PREFIX", "note")

app = FastAPI(title="__NAME__", version="0.1.0")
stats = {"calls": 0, "notes": 0, "day": datetime.now().date(), "last_used": time.time()}
calls_by_hour: dict[int, int] = {}


def used() -> None:
    stats["calls"] += 1
    stats["last_used"] = time.time()
    hour = int(time.time() // 3600 * 3600)
    calls_by_hour[hour] = calls_by_hour.get(hour, 0) + 1


@app.get("/health")
def health() -> dict:
    """AIHub polls this; any 2xx means ready."""
    return {"status": "ok"}


@app.get("/v1/status")
def status() -> dict:
    """Optional (architecture §4.6). Numeric stats are charted automatically."""
    if stats["day"] != datetime.now().date():
        stats["day"], stats["notes"] = datetime.now().date(), 0
    return {
        "loaded": None,  # this mod holds no models
        "busy": False,
        "idle_s": round(time.time() - stats["last_used"], 1),
        "stats": [
            {"label": "Calls", "value": stats["calls"]},
            {"label": "Notes today", "value": stats["notes"], "reset": "daily"},
        ],
        "jobs": [],
    }


@app.get("/v1/hello", summary="Say hello")
def hello(name: str = "world") -> dict:
    used()
    return {"message": f"Hello, {name}!"}


class Echo(BaseModel):
    message: str = Field(description="Anything")
    tags: list[str] = Field(default_factory=list, description="Tags")


@app.post("/v1/echo", summary="Echo a JSON body")
def echo(body: Echo) -> dict:
    used()
    return body.model_dump()


class Note(BaseModel):
    text: str = Field(description="What the note says", min_length=1)
    title: str | None = Field(None, description="Shown on the Outputs page")


@app.post("/v1/note", summary="Write a text note to Outputs", status_code=201)
def note(body: Note) -> dict:
    """Outputs follow architecture §4.7: <outputs>/<date>/<HHMMSS>-<slug>.<ext>, written
    as .part then renamed, with an optional <file>.json sidecar."""
    used()
    now = datetime.now()
    day = OUTPUTS / now.strftime("%Y-%m-%d")
    day.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", (body.title or body.text).lower()).strip("-")[:40] or PREFIX
    path = day / f"{now.strftime('%H%M%S')}-{slug}.txt"
    part = path.with_name(path.name + ".part")
    part.write_text(body.text)
    part.rename(path)
    sidecar = {"title": body.title or body.text[:60], "kind": "text", "prompt": body.text, "source": {"service": "__ID__"}}
    path.with_name(path.name + ".json").write_text(json.dumps(sidecar))
    stats["notes"] += 1
    return {"path": str(path)}


@app.get("/v1/widgets/calls", summary="Calls per hour (dashboard widget)")
def calls_widget(span: str = Query("24h", alias="range", description="1h, 6h, 24h, 7d or 30d")) -> dict:
    """WidgetData (design brief §11.7) for the [[ui.widgets]] entry in service.toml."""
    now = int(time.time() // 3600 * 3600)
    hours = [now - 3600 * i for i in range(23, -1, -1)]
    return {"unit": "calls", "t": hours, "series": [{"name": "Calls", "values": [calls_by_hour.get(h, 0) for h in hours]}]}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="info")
