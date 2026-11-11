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


class _More:
    """Phase 5: the settings, tools and the chat's own model."""

    async def voice_mode(self) -> dict[str, Any]:
        """`[voice_mode]` from the hub's settings ({} when the hub doesn't answer)."""
        if not self.url:
            return {}
        try:
            async with self._client() as c:
                r = await c.get("/api/settings")
            return (r.json().get("voice_mode") or {}) if r.status_code == 200 else {}
        except (httpx.HTTPError, ValueError):
            return {}

    async def tool(self, name: str) -> dict[str, Any]:
        """One tool as a model reads it (`GET /api/tools?names=&view=model`)."""
        try:
            async with self._client() as c:
                r = await c.get("/api/tools", params={"names": name, "view": "model"})
        except httpx.HTTPError as e:
            raise HubError(502, f"GAIFA didn't answer for the tool {name} ({e})", "hub_unreachable") from e
        if r.status_code >= 400 or not r.json():
            raise HubError(r.status_code, _detail(r) or f"no tool {name}", "unknown_tool")
        return r.json()[0]

    async def call_tool(self, name: str, arguments: dict[str, Any], thread: str | None, wait: float = 25) -> dict[str, Any]:
        """Run a tool as an unattended call of this chat: what would ask is refused, never a card."""
        origin = {"service": self.service, "unattended": True, **({"thread": thread} if thread else {})}
        try:
            async with self._client(read=wait + 10) as c:
                r = await c.post(f"/api/tools/{name}/call", params={"wait": wait},
                                 json={"arguments": arguments, "origin": origin, "mode": "manual"})
        except httpx.HTTPError as e:
            raise HubError(502, f"GAIFA didn't answer for {name} ({e})", "hub_unreachable") from e
        if r.status_code >= 400:
            raise HubError(r.status_code, _detail(r), "tool_failed")
        return r.json()

    async def voice_ask(self, thread: str, text: str) -> dict[str, Any]:
        """Send the question to the chat as a message (the agent's /voice-ask): {seq}."""
        try:
            async with self._client() as c:
                r = await c.post(f"/api/s/agent/v1/threads/{thread}/voice-ask", json={"text": text})
        except httpx.HTTPError as e:
            raise HubError(502, f"the chat didn't answer ({e})", "hub_unreachable") from e
        if r.status_code >= 400:
            raise HubError(r.status_code, _detail(r), "ask_failed")
        return r.json()

    async def voice_answer(self, thread: str, after: int, wait_s: float) -> dict[str, Any]:
        """The chat's answer to it, waiting for the turn to end: {state: done | running | waiting, text}."""
        import asyncio
        import time

        deadline = time.monotonic() + wait_s
        out: dict[str, Any] = {"state": "running", "text": ""}
        while time.monotonic() < deadline:
            try:
                async with self._client(read=40) as c:
                    r = await c.get(f"/api/s/agent/v1/threads/{thread}/voice-answer", params={"after": after, "wait": 25})
            except httpx.HTTPError as e:
                raise HubError(502, f"the chat didn't answer ({e})", "hub_unreachable") from e
            if r.status_code >= 400:
                raise HubError(r.status_code, _detail(r), "ask_failed")
            out = r.json()
            if out.get("state") == "done":
                return out
            await asyncio.sleep(0.2)
        return out


class Hub(_More):
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
