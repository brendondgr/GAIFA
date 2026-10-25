"""GAIFA over HTTP (architecture §7, §8): ask for memory before an engine starts, register downloads.
Without a hub (no GAIFA_URL) there is nothing to ask."""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

log = logging.getLogger("vllm")


class NeedsRoom(Exception):
    """The hub's 409: its body (`detail`, `code`, `data.plan`) is passed on to the caller unchanged, so
    the page's Make-room dialog can show the plan."""

    def __init__(self, body: dict[str, Any]):
        super().__init__(body.get("detail") or "not enough free memory")
        self.body = body


class Hub:
    def __init__(self, url: str | None, transport: httpx.AsyncBaseTransport | None = None):
        self.url = (url or "").rstrip("/") or None
        self.service = os.environ.get("GAIFA_SERVICE_ID", "vllm")
        self.transport = transport

    def _client(self, read: float = 30) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self.url or "", timeout=httpx.Timeout(10, read=read), transport=self.transport)

    async def acquire(self, gb: float, reason: str, make_room: bool) -> dict[str, Any] | None:
        if not self.url or gb <= 0:
            return None
        try:
            async with self._client(read=180) as c:     # making room unloads other mods first
                r = await c.post("/api/memory/acquire", params={"make_room": "1"} if make_room else None,
                                 json={"service": self.service, "needs_bytes": int(gb * 1e9), "reason": reason})
        except httpx.HTTPError as e:
            log.warning("GAIFA not reachable for memory (%s); starting anyway", e)
            return None
        if r.status_code == 409:
            raise NeedsRoom(r.json())
        if r.status_code >= 400:
            log.warning("memory acquire answered %s: %s", r.status_code, r.text[:200])
            return None
        return r.json()

    async def register_model(self, entry: dict[str, Any]) -> str:
        """POST /api/models; an existing entry (409 model_exists) is fine. Returns 'registered',
        'exists', 'no hub' or the error."""
        if not self.url:
            return "no hub"
        try:
            async with self._client() as c:
                r = await c.post("/api/models", json=entry)
        except httpx.HTTPError as e:
            return f"GAIFA not reachable ({e})"
        if r.status_code < 300:
            return "registered"
        if r.status_code == 409:
            return "exists"
        return f"HTTP {r.status_code}: {r.text[:200]}"
