"""A job's live progress (plan 45.3; GAIFA's shape, plan 44.2): its stages with their state and time left, the running
stage's steps, and a preview: the cut-out the engines read (`input_rgba.png`) while the shape is made, then the
rendered views (`preview.png`) once they exist. Paths are this mod's (`/v1/jobs/{id}/files/…`); GAIFA rewrites them."""

from __future__ import annotations

from pathlib import Path
from typing import Any

LABELS = {"shape": "Shape", "parts": "Parts", "rig": "Rig", "preview": "Views"}
STATES = {"pending": "waiting", "running": "running", "done": "done", "skipped": "skipped", "failed": "failed",
          "canceled": "failed"}


def live_of(job: dict[str, Any], sched: dict[str, Any] | None, jdir: Path | None) -> dict[str, Any] | None:
    """`live` for a queued or running job; None once it's finished."""
    status = job.get("status")
    if status not in ("queued", "running"):
        return None
    stages = job.get("stages") or {}
    by = (sched or {}).get("by_stage") or {}
    out: dict[str, Any] = {"stages": [{"id": s, "label": LABELS.get(s, s.title()), "state": STATES.get(v.get("state"), "waiting"),
                                       **({"eta_s": by[s]} if s in by else {})} for s, v in stages.items()]}
    running = next((s for s, v in stages.items() if v.get("state") == "running"), None)
    out["stage"] = "queued" if status == "queued" else (running or "starting")
    if running and stages[running].get("total"):
        out.update(step=int(stages[running].get("step") or 0), steps=int(stages[running]["total"]))
    if sched and sched.get("eta_s") is not None:
        out["eta_s"] = sched["eta_s"]
    if jdir is not None:
        jid = job["id"]
        if (jdir / "preview.png").is_file():
            out["preview"] = {"url": f"/v1/jobs/{jid}/files/preview.png", "seq": 2}
        elif (jdir / "input_rgba.png").is_file():
            out["preview"] = {"url": f"/v1/jobs/{jid}/files/input_rgba.png", "seq": 1}
    return out
