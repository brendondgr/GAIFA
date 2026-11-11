"""What this mod asks of GAIFA, over HTTP: memory before a load, a chat's context, and writing a turn into it."""

from __future__ import annotations

import logging
from typing import Any

import httpx

log = logging.getLogger(__name__)


class HubError(Exception):
    def __init__(self, status: int, detail: str, code: str, data: Any = None) -> None:
        super().__init__(detail)
        self.status, self.detail, self.code, self.data = status, detail, code, data


class Hub:
    def __init__(self, url: str, service: str = "voice") -> None:
        self.url, self.service = url.rstrip("/"), service

    def _client(self, read: float = 30) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self.url, timeout=httpx.Timeout(10, read=read))

    async def acquire(self, gb: float, reason: str, make_room: bool = False) -> None:
        """Ask for memory before the model loads; a 409 needs_room is passed on unchanged."""
        if not self.url or gb <= 0:
            return
        try:
            async with self._client(read=180) as c:
                r = await c.post("/api/memory/acquire", params={"make_room": "1"} if make_room else None,
                                 json={"service": self.service, "needs_bytes": int(gb * 1e9), "reason": reason})
        except httpx.HTTPError as e:
            log.warning("GAIFA not reachable for memory (%s); loading anyway", e)
            return
        if r.status_code == 409:
            b = r.json()
            raise HubError(409, b.get("detail") or "not enough free memory", b.get("code") or "needs_room", b.get("data"))
        if r.status_code >= 400:
            log.warning("memory acquire answered %s: %s", r.status_code, r.text[:200])

    async def voice_context(self, thread: str) -> dict[str, Any]:
        """The chat's instructions and last turns for a voice session (the agent's /voice-context)."""
        if not self.url:
            return {}
        try:
            async with self._client() as c:
                r = await c.get(f"/api/s/agent/v1/threads/{thread}/voice-context")
        except httpx.HTTPError as e:
            raise HubError(502, f"GAIFA didn't answer for the chat's context ({e})", "hub_unreachable") from e
        if r.status_code == 404:
            raise HubError(404, f"no chat {thread!r}", "not_found")
        if r.status_code >= 400:
            raise HubError(r.status_code, _detail(r), "context_failed")
        return r.json()

    async def voice_turn(self, thread: str, turn: dict[str, Any]) -> dict[str, Any] | None:
        """Write one spoken turn into the chat; a failure is logged and returned as None (the talk goes on)."""
        if not self.url:
            return None
        try:
            async with self._client() as c:
                r = await c.post(f"/api/s/agent/v1/threads/{thread}/voice-turn", json=turn)
        except httpx.HTTPError as e:
            log.warning("voice turn not written to %s: %s", thread, e)
            return None
        if r.status_code >= 400:
            log.warning("voice turn not written to %s: HTTP %s %s", thread, r.status_code, _detail(r))
            return None
        return r.json()


def _detail(r: httpx.Response) -> str:
    try:
        return str(r.json().get("detail") or r.text[:200])
    except ValueError:
        return r.text[:200]
