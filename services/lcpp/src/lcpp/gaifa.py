"""Calls back into GAIFA when lcpp runs as its `lcpp` mod (GAIFA_URL is set; GAIFA architecture
§4.2 "Call back into the hub"). Without GAIFA_URL every function here is a no-op, so lcpp still
works on its own.

- ``acquire``: ask for memory before a launch (``POST /api/memory/acquire``). A 409 from GAIFA
  means other mods would have to be unloaded: the launch fails with ``needs_room`` and the plan,
  unless the caller asked to make room (the UI's "Unload & continue").
- ``register_download``: record a finished Hugging Face download in GAIFA's models registry.
  Best effort: a failure is logged, never raised.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import httpx

from lcpp.instances import LcppError

log = logging.getLogger("lcpp.gaifa")
SERVICE = os.environ.get("GAIFA_SERVICE_ID") or "lcpp"
TIMEOUT = httpx.Timeout(10.0, read=120.0)  # making room can take a while (unloads)


def hub_url() -> str | None:
    url = os.environ.get("GAIFA_URL", "").strip().rstrip("/")
    return url or None


def page_url() -> str | None:
    """The Launcher page inside GAIFA (the relay links lcpp's endpoints to it)."""
    url = hub_url()
    return f"{url}/#/s/{SERVICE}" if url else None


async def acquire(needs_bytes: int, make_room: bool, reason: str,
                  transport: httpx.AsyncBaseTransport | None = None) -> dict[str, Any] | None:
    """The grant, or None when GAIFA isn't there. Raises LcppError("needs_room") on a 409."""
    url = hub_url()
    if not url:
        return None
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, transport=transport) as c:
            r = await c.post(f"{url}/api/memory/acquire", params={"make_room": "1"} if make_room else None,
                             json={"service": SERVICE, "needs_bytes": int(needs_bytes), "reason": reason})
    except httpx.HTTPError as e:
        log.warning("GAIFA not reachable for memory acquire (%s); launching anyway", e)
        return None
    if r.status_code == 409:
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        plan = (body.get("data") or {}).get("plan")
        err = LcppError("needs_room", body.get("detail") or "Not enough free memory", 409)
        err.data = {"plan": plan} if plan else None
        raise err
    if r.status_code >= 400:
        log.warning("GAIFA memory acquire answered %s: %s; launching anyway", r.status_code, r.text[:200])
        return None
    return r.json()


def models_root() -> Path | None:
    m = os.environ.get("GAIFA_MODELS")
    return Path(m) if m else None


async def register_download(dest_dir: Path, *, model_id: str | None, name: str, repo: str, revision: str,
                            files: list[tuple[Path, str | None]],
                            transport: httpx.AsyncBaseTransport | None = None) -> str | None:
    """POST /api/models for a finished download folder. Returns a warning, or None when it worked
    (or there is no GAIFA)."""
    url, root = hub_url(), models_root()
    if not url or not root:
        return None
    try:
        rel = dest_dir.resolve().relative_to(root.resolve())
    except ValueError:
        return f"not registered in GAIFA: {dest_dir} is outside {root}"
    body = {
        "path": rel.as_posix(), "kind": "llm", "name": name, "services": [SERVICE],
        "source": {"type": "huggingface", "repo": repo, "revision": revision},
        "files": [{"path": (rel / p.name).as_posix(), "role": "weights" if i == 0 else "sidecar",
                   **({"sha256": sha} if sha else {})} for i, (p, sha) in enumerate(files)],
    }
    if model_id:
        body["id"] = model_id.lower()
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, transport=transport) as c:
            r = await c.post(f"{url}/api/models", json=body)
    except httpx.HTTPError as e:
        log.warning("could not register %s in GAIFA: %s", rel, e)
        return f"not registered in GAIFA: {e}"
    if r.status_code >= 400:
        detail = r.json().get("detail") if r.headers.get("content-type", "").startswith("application/json") else r.text
        log.warning("GAIFA refused to register %s: %s", rel, detail)
        return f"not registered in GAIFA: {detail}"
    return None
