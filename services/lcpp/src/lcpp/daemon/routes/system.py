"""Health, overview, system facts, settings, recent launches, port suggestion."""

from __future__ import annotations

import asyncio
import functools
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, Request

from lcpp import __version__, proc, settings as settings_mod
from lcpp.cmdline import binary_path
from lcpp.daemon.app import state

router = APIRouter(prefix="/api", tags=["system"])

BUILD_RE = re.compile(r"(?:llama-)?b(\d{3,})")
VERSION_RE = re.compile(r"version:\s*(\d+)")


@functools.lru_cache(maxsize=4)
def _llama_build(binary: str, _mtime: float) -> str:
    """``b9692`` from the install dir name (runtime/llama.cpp/bin/llama-b9692),
    else from ``llama-server --version``."""
    resolved = Path(binary).resolve()
    m = BUILD_RE.search(resolved.parent.name)
    if m:
        return f"b{m.group(1)}"
    try:
        out = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=10)
        v = VERSION_RE.search(out.stdout + out.stderr)
        return f"b{v.group(1)}" if v else "unknown"
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"


def system_view(request: Request) -> dict[str, Any]:
    st = state(request)
    binary = binary_path(st.paths, st.settings)
    ok = binary.is_file() and os.access(binary, os.X_OK)
    return {
        "memory": proc.meminfo(),
        "gpu": proc.gpu(),
        "daemon": {"version": __version__, "pid": os.getpid(), "rss_bytes": proc.rss_bytes(os.getpid()),
                   "uptime_s": int(time.time() - st.started), "port": st.settings["daemon"]["port"]},
        "llama": {"build": _llama_build(str(binary), binary.stat().st_mtime) if ok else "missing",
                  "binary": st.settings["llama"]["binary"], "binary_ok": ok},
    }


@router.get("/health")
async def health(request: Request):
    st = state(request)
    return {"ok": True, "version": __version__, "instances": len(st.supervisor.instances)}


@router.get("/overview")
async def overview(request: Request):
    st = state(request)
    instances, system, relay = await asyncio.gather(
        st.supervisor.views(), asyncio.to_thread(system_view, request), st.relay.status())
    return {"instances": instances, "system": system, "relay": relay}


@router.get("/system")
async def system(request: Request):
    return await asyncio.to_thread(system_view, request)


@router.get("/settings")
async def get_settings(request: Request):
    return state(request).settings


@router.put("/settings")
async def put_settings(request: Request, body: dict[str, Any] = Body(...)):
    st = state(request)
    old_port = st.settings["daemon"]["port"]
    new = await asyncio.to_thread(settings_mod.save, st.paths, body)
    # Everything but the daemon's own port applies live: the supervisor and
    # relay registrar read the same dict.
    st.settings.clear()
    st.settings.update(new)
    await st.relay.settings_changed()
    return {"settings": new, "restart_required": new["daemon"]["port"] != old_port}


@router.get("/recent")
async def recent(request: Request):
    return state(request).supervisor.recent()


@router.get("/ports/suggest")
async def suggest_port(request: Request):
    return {"port": await asyncio.to_thread(state(request).supervisor.suggest_port)}
