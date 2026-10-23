"""A job's live progress (plan 44.2): the `live` object a mod may put on a job's status and on its status `jobs[]`.

    {"stage": "sampling", "stages": [{"id", "label", "state", "eta_s"}], "step": 3, "steps": 8, "eta_s": 6.5,
     "preview": {"url": "/v1/runs/r-1/preview", "seq": 3, "w": 1184, "h": 896}, "lines": [5, 16],
     "audio": "/v1/speech/jobs/s-1/audio", "frames": 49}

Every field is optional. `preview.url` and `audio` are paths on the mod; the hub rewrites them to its proxy
(`/api/s/<id>/…`) so a browser can fetch them. Whatever shows the job (a chat card, the Overview's thumbnail, a mod
page) pulls the preview frame itself when `preview.seq` changes, so events stay small.
"""

from __future__ import annotations

import json
from typing import Any

CAP_BYTES = 4096
STAGE_STATES = {"waiting", "running", "done", "failed", "skipped"}


def _num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _path(sid: str, v: Any) -> str | None:
    """A mod's path → the hub's proxy path; a path already on the hub (`/api/…`) is kept; anything else is dropped."""
    if not isinstance(v, str) or not v.startswith("/") or v.startswith("//") or len(v) > 400:
        return None
    return v if v.startswith("/api/") else f"/api/s/{sid}{v}"


def clean(live: Any, sid: str) -> dict[str, Any] | None:
    """A mod's `live` → the hub's: known fields with the right types, paths rewritten, at most CAP_BYTES of JSON."""
    if not isinstance(live, dict):
        return None
    out: dict[str, Any] = {}
    if isinstance(live.get("stage"), str) and live["stage"]:
        out["stage"] = live["stage"][:40]
    for k in ("step", "steps", "frames"):
        if _num(live.get(k)) and live[k] >= 0:
            out[k] = int(live[k])
    if _num(live.get("eta_s")) and live["eta_s"] >= 0:
        out["eta_s"] = round(float(live["eta_s"]), 1)
    if isinstance(live.get("stages"), list):
        stages = []
        for st in live["stages"][:12]:
            if not isinstance(st, dict) or not isinstance(st.get("id"), str):
                continue
            s: dict[str, Any] = {"id": st["id"][:40], "label": str(st.get("label") or st["id"])[:60],
                                 "state": st.get("state") if st.get("state") in STAGE_STATES else "waiting"}
            if _num(st.get("eta_s")):
                s["eta_s"] = round(float(st["eta_s"]), 1)
            stages.append(s)
        out["stages"] = stages
    p = live.get("preview")
    if isinstance(p, dict) and (url := _path(sid, p.get("url"))):
        prev: dict[str, Any] = {"url": url, "seq": int(p["seq"]) if _num(p.get("seq")) else 0}
        for k in ("w", "h"):
            if _num(p.get(k)) and p[k] > 0:
                prev[k] = int(p[k])
        out["preview"] = prev
    lines = live.get("lines")
    if isinstance(lines, list) and len(lines) == 2 and all(_num(x) for x in lines):
        out["lines"] = [int(lines[0]), int(lines[1])]
    if audio := _path(sid, live.get("audio")):
        out["audio"] = audio
    while out and len(json.dumps(out)) > CAP_BYTES:       # the stages list is the only part that can be long
        if out.get("stages"):
            out["stages"] = out["stages"][:-1]
        else:
            break
    return out or None


def key(live: dict[str, Any] | None) -> tuple[Any, ...] | None:
    """What a change is worth publishing for: the stage, the step, a new preview frame, lines done, stage states."""
    if not live:
        return None
    return (live.get("stage"), live.get("step"), (live.get("preview") or {}).get("seq"), tuple(live.get("lines") or ()),
            tuple((s["id"], s["state"]) for s in live.get("stages") or ()))
