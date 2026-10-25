"""The `system` area: `GET /api/system` and `GET /config.js`."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import time
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from fastapi.responses import Response

from utils import doctor
from utils import hardware, proc
from utils.api_models import Doctor, Hardware, SystemInfo

router = APIRouter(tags=["system"])

USAGE_TTL_S = 60.0
_usage_cache: dict[tuple[str, ...], tuple[float, dict[str, int]]] = {}


def dir_bytes(path: Path) -> int:
    """Apparent size of every file under `path`, without following symlinks."""
    total = 0
    for dirpath, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.lstat(os.path.join(dirpath, name)).st_size
            except OSError:
                pass
    return total


def rss_bytes(pid: int | None = None) -> int:
    return proc.rss_bytes(pid or os.getpid())


USAGE_KEYS = ("models_bytes", "databases_bytes", "outputs_bytes", "logs_bytes", "state_bytes")


async def _usage(*dirs: Path) -> dict[str, int]:
    """Sizes of models, databases, outputs, logs and state (cached for a minute)."""
    key = tuple(str(d) for d in dirs)
    hit = _usage_cache.get(key)
    if hit and time.monotonic() - hit[0] < USAGE_TTL_S:
        return hit[1]
    sizes = await asyncio.gather(*(asyncio.to_thread(dir_bytes, p) for p in dirs))
    usage = dict(zip(USAGE_KEYS, sizes))
    _usage_cache[key] = (time.monotonic(), usage)
    return usage


@router.get("/api/system", summary="Hub version, process, paths and disk usage", response_model=SystemInfo)
async def get_system(request: Request) -> dict:
    return await system_info(request.app.state.hub)


async def system_info(hub: Any) -> dict[str, Any]:
    """The brief's `System` (also part of `GET /api/overview`)."""
    p = hub.paths
    disk = shutil.disk_usage(p.root)
    return {
        "hub": {
            "version": hub.version,
            "pid": os.getpid(),
            "uptime_s": round(time.time() - hub.started_ts),
            "rss_bytes": rss_bytes(),
            "port": hub.port,
        },
        "paths": {"root": str(p.root), "models": str(p.models), "databases": str(p.databases), "outputs": str(p.outputs),
                  "logs": str(p.logs), "state": str(p.state)},
        "usage": await _usage(p.models, p.databases, p.outputs, p.logs, p.state),
        "disk": {"free_bytes": disk.free, "total_bytes": disk.total},
    }


@router.get("/api/system/hardware", summary="What this machine has: OS, GPUs, their memory and runtimes, the usable accelerators", response_model=Hardware)
async def get_hardware(refresh: bool = False) -> dict:
    """Read once and cached; `?refresh=true` reads the machine again (plan 35.2)."""
    return (await asyncio.to_thread(hardware.detect, refresh)).to_dict()


@router.get("/api/doctor", summary="Install checks: models on disk, manifests, paths outside the project, ports, units, disk, offline mods", response_model=Doctor, response_model_exclude_none=True)
async def get_doctor(request: Request) -> dict:
    return await doctor.run(request.app.state.hub)


class InventoryItem(BaseModel):
    path: str
    kind: Literal["allowlisted", "runtime", "outside"]
    used_by: str
    reason: str


class Inventory(BaseModel):
    ok: bool = Field(description="Nothing outside the allowlist (runtime leftovers are fine)")
    counts: dict[str, int]
    items: list[InventoryItem]


@router.get("/api/doctor/inventory", summary="Every path outside the project that anything uses, with its reason (plan 16.3)",
            response_model=Inventory)
async def get_inventory(request: Request) -> dict:
    from utils.inventory import inventory

    return await asyncio.to_thread(inventory, request.app.state.hub)


@router.get("/config.js", include_in_schema=False)
async def config_js(request: Request) -> Response:
    hub = request.app.state.hub
    body = f'window.GAIFA_API_BASE = "";\nwindow.GAIFA_LIVE_AREAS = {json.dumps(hub.live_areas)};\n'
    return Response(body, media_type="text/javascript", headers={"Cache-Control": "no-store"})
