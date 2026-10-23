"""Status polling for mods with `[run] status` (plan 2.4, architecture §4.6).

`validate()` normalizes a status body and lists what is wrong with it, so the
poller keeps the good parts and `aihub check` (2.10) can report the rest.
"""

from __future__ import annotations

import asyncio
import math
import re
import time
from typing import TYPE_CHECKING, Any

import httpx

from utils import live

if TYPE_CHECKING:
    from utils.services import Service, ServiceManager

MAX_STATS = 4
JOB_STATES = {"queued", "running", "done", "failed", "cancelled"}
ACTIVE_JOBS = {"queued", "running"}


def slug(label: str) -> str:
    """`"Clips today"` → `clips_today` (the metric series is `svc.<id>.stat.<slug>`)."""
    return re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_") or "stat"


def validate(body: Any) -> tuple[dict[str, Any], list[str]]:
    """A status body → (normalized fields, problems). Unknown keys are ignored."""
    out: dict[str, Any] = {"loaded": None, "busy": False, "idle_s": None, "memory_estimate_gb": None, "stats": [], "jobs": []}
    problems: list[str] = []
    if not isinstance(body, dict):
        return out, [f"status must be a JSON object, got {type(body).__name__}"]

    loaded = body.get("loaded")
    if loaded is None or isinstance(loaded, bool):
        out["loaded"] = loaded
    else:
        problems.append("loaded must be true, false or null")

    busy = body.get("busy", False)
    if isinstance(busy, bool):
        out["busy"] = busy
    else:
        problems.append("busy must be true or false")

    for key in ("idle_s", "memory_estimate_gb"):
        v = body.get(key)
        if v is None:
            continue
        if _number(v) and v >= 0:
            out[key] = float(v)
        else:
            problems.append(f"{key} must be a number ≥ 0 or null")

    stats = body.get("stats", [])
    if not isinstance(stats, list):
        problems.append("stats must be a list")
        stats = []
    if len(stats) > MAX_STATS:
        problems.append(f"stats has {len(stats)} entries; at most {MAX_STATS} are shown")
    for i, s in enumerate(stats[:MAX_STATS]):
        if not isinstance(s, dict) or not isinstance(s.get("label"), str) or not s["label"]:
            problems.append(f"stats[{i}] needs a non-empty label")
            continue
        v = s.get("value")
        if not (_number(v) or isinstance(v, str)):
            problems.append(f"stats[{i}] ({s['label']}): value must be a number or a string")
            continue
        stat: dict[str, Any] = {"label": s["label"], "value": v}
        for opt in ("unit", "hint"):
            if isinstance(s.get(opt), str):
                stat[opt] = s[opt]
        if s.get("reset") is not None:
            if s["reset"] == "daily":
                stat["reset"] = "daily"
            else:
                problems.append(f"stats[{i}] ({s['label']}): reset must be \"daily\"")
        out["stats"].append(stat)

    jobs = body.get("jobs", [])
    if not isinstance(jobs, list):
        problems.append("jobs must be a list")
        jobs = []
    for i, j in enumerate(jobs):
        if not isinstance(j, dict) or not isinstance(j.get("id"), str) or not j["id"]:
            problems.append(f"jobs[{i}] needs a string id")
            continue
        state = j.get("state", "running")
        if state not in JOB_STATES:
            problems.append(f"jobs[{i}] ({j['id']}): state must be one of {', '.join(sorted(JOB_STATES))}")
            continue
        progress = j.get("progress")
        if progress is not None and not (_number(progress) and 0 <= progress <= 1):
            problems.append(f"jobs[{i}] ({j['id']}): progress must be between 0 and 1, or null")
            progress = None
        job: dict[str, Any] = {"id": j["id"], "label": str(j.get("label") or j["id"]), "progress": progress, "state": state}
        if isinstance(j.get("stage"), str) and j["stage"]:      # e.g. "waiting_gpu" (plan 31.3), with what runs before it
            job["stage"] = j["stage"][:40]
            if isinstance(j.get("ahead"), list):
                job["ahead"] = [a for a in j["ahead"][:10] if isinstance(a, dict)]
            if _number(j.get("eta_s")):
                job["eta_s"] = float(j["eta_s"])
        if isinstance(j.get("live"), dict):                       # plan 44.2: cleaned with the mod's id in _publish_jobs
            job["live"] = j["live"]
        if isinstance(j.get("route"), str):
            if j["route"].startswith("#/"):              # a page in the UI; it becomes a link's href
                job["route"] = j["route"]
            else:
                problems.append(f"jobs[{i}] ({j['id']}): route must start with \"#/\" (a page in AIHub)")
        out["jobs"].append(job)
    return out, problems


def _number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


async def fetch(mgr: ServiceManager, svc: Service) -> tuple[dict[str, Any] | None, list[str]]:
    """GET the status route: (normalized, problems), or (None, [why]) when it can't be read."""
    assert svc.m and svc.m.run.status
    try:
        r = await mgr.client.get(svc.url + svc.m.run.status, timeout=mgr.t.health_timeout_s)
    except httpx.HTTPError as e:
        return None, [f"GET {svc.m.run.status}: {type(e).__name__}"]
    if not 200 <= r.status_code < 300:
        return None, [f"GET {svc.m.run.status}: HTTP {r.status_code}"]
    try:
        body = r.json()
    except ValueError:
        return None, [f"GET {svc.m.run.status}: not JSON"]
    svc.status = body if isinstance(body, dict) else None
    return validate(body)


def load_from(svc: Service, loaded: bool | None) -> str:
    """The load state a status report implies. Without `loaded`, mods with [memory] keep the hub's own view."""
    if loaded is True:
        return "loaded"
    if loaded is False:
        return "unloaded"
    return svc.load if svc.has_memory else "n/a"


def apply(mgr: ServiceManager, svc: Service, st: dict[str, Any], asked_at: float | None = None) -> bool:
    """Fold a normalized status into the service. Returns True when the UI should hear about it. `asked_at`
    (time.monotonic() when the status was requested): if the hub set the load state after that, the report's
    `loaded` is stale (it was read before the load or unload finished) and the hub's own state stays."""
    before = (svc.load, svc.busy, svc.stats, svc.memory_estimate_gb, _job_view(svc.jobs))
    new_load = load_from(svc, st["loaded"])
    if asked_at is not None and svc.load_set_at > asked_at:
        new_load = svc.load
    # A load/unload the hub started stays "loading"/"unloading" until the mod confirms the result.
    if svc.load == "loading" and new_load == "unloaded":
        new_load = "loading"
    if svc.load == "unloading" and new_load == "loaded":
        new_load = "unloading"
    svc.load = new_load
    svc.busy = st["busy"]
    svc.idle_s = st["idle_s"]
    svc.stats = st["stats"]
    svc.memory_estimate_gb = st["memory_estimate_gb"]
    _publish_jobs(mgr, svc, st["jobs"])
    after = (svc.load, svc.busy, svc.stats, svc.memory_estimate_gb, _job_view(svc.jobs))
    return before != after


def _job_view(jobs: list[dict[str, Any]]) -> list[tuple[Any, ...]]:
    return [(j["id"], j["state"], j["progress"], j["label"], j.get("stage"), live.key(j.get("live"))) for j in jobs]


def _publish_jobs(mgr: ServiceManager, svc: Service, jobs: list[dict[str, Any]]) -> None:
    old = {j["id"]: j for j in svc.jobs}
    new = {j["id"]: _with_live({**j, "service": svc.id}, svc.id) for j in jobs}
    for jid, job in new.items():
        if old.get(jid) != job:
            mgr.bus.publish({"type": "job", "job": job})
    for jid, job in old.items():
        if jid not in new and job["state"] in ACTIVE_JOBS:
            # Gone from the list while still active: the mod finished it without reporting a final state.
            mgr.bus.publish({"type": "job", "job": {**job, "state": "done", "progress": 1.0 if job["progress"] is not None else None}})
    svc.jobs = list(new.values())


def _with_live(job: dict[str, Any], sid: str) -> dict[str, Any]:
    lv = live.clean(job.pop("live", None), sid)
    return {**job, "live": lv} if lv else job


def interval(mgr: ServiceManager, svc: Service) -> float:
    active = svc.load in ("loading", "unloading") or svc.busy or any(j["state"] in ACTIVE_JOBS for j in svc.jobs)
    return mgr.t.status_busy_s if active else mgr.t.status_idle_s


async def poll(mgr: ServiceManager, svc: Service, gen: int) -> None:
    """Poll while the service is up; every 2 s while loading, busy or running jobs, else every 10 s."""
    while gen == svc.gen:
        if svc.state == "ready":
            asked_at = time.monotonic()
            st, _ = await fetch(mgr, svc)
            if gen != svc.gen:
                return
            if st is not None:
                svc.status_ts = time.time()
                if apply(mgr, svc, st, asked_at):
                    mgr._publish(svc)
        await asyncio.sleep(interval(mgr, svc))
