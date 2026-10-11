"""Asking AIHub for memory (architecture §7): a local image engine acquires its own amount before its
worker loads, so switching from a small engine to a big one makes room first. Without AIHub (no
AIHUB_URL) there is nothing to ask."""

from __future__ import annotations

import logging
import os

import httpx

log = logging.getLogger("gen3d.hub")


class NeedsRoom(RuntimeError):
    pass


async def acquire(gb: float, reason: str, hub_url: str | None = None, transport=None) -> None:
    hub = (hub_url or os.environ.get("AIHUB_URL") or "").rstrip("/")
    if not hub or gb <= 0:
        return
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10, read=180), transport=transport) as c:
            # The job was queued by someone who asked for it: unloading other mods to run it is expected.
            r = await c.post(f"{hub}/api/memory/acquire", params={"make_room": "1"},
                             json={"service": os.environ.get("AIHUB_SERVICE_ID", "gen3d"), "needs_bytes": int(gb * 1e9),
                                   "reason": reason})
    except httpx.HTTPError as exc:
        log.warning("AIHub not reachable for memory (%s); running anyway", exc)
        return
    if r.status_code == 409:
        raise NeedsRoom(r.json().get("detail") or "not enough free memory")
    if r.status_code >= 400:
        log.warning("memory acquire answered %s: %s", r.status_code, r.text[:200])
