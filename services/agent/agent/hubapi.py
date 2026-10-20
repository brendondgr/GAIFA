"""AIHub over HTTP (the only way a mod talks to the hub): tools, calls, approvals, outputs,
skills and the event stream."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

log = logging.getLogger("agent.hub")


class HubAPI:
    def __init__(self, url: str) -> None:
        self.url = url.rstrip("/")
        self.client = httpx.AsyncClient(base_url=self.url, trust_env=False, timeout=httpx.Timeout(120, connect=5))
        self._index: tuple[float, list[dict[str, Any]]] = (0.0, [])
        self._full: dict[str, tuple[float, dict[str, Any]]] = {}

    async def close(self) -> None:
        await self.client.aclose()

    async def _json(self, method: str, path: str, **kw: Any) -> Any:
        r = await self.client.request(method, path, **kw)
        if r.status_code >= 400:
            try:
                body = r.json()
            except ValueError:
                body = {"detail": r.text[:300]}
            raise HubCallError(r.status_code, body.get("code") or "hub_error", body.get("detail") or str(body), body.get("data"))
        return r.json() if r.content else None

    # ---- tools -------------------------------------------------------------------------------

    async def index(self, max_age: float = 10) -> list[dict[str, Any]]:
        ts, cached = self._index
        if cached and time.time() - ts < max_age:
            return cached
        data = await self._json("GET", "/api/tools/index")
        self._index = (time.time(), data)
        return data

    async def tools(self, names: list[str]) -> list[dict[str, Any]]:
        """Full schemas, cached for 30 s each."""
        now = time.time()
        want = [n for n in names if n not in self._full or now - self._full[n][0] > 30]
        if want:
            try:
                for t in await self._json("GET", "/api/tools", params={"names": ",".join(want), "view": "model"}):
                    self._full[t["name"]] = (now, t)
            except HubCallError as e:
                if e.code != "unknown_tool":
                    raise
                for n in want:   # one at a time, skipping the unknown ones
                    try:
                        for t in await self._json("GET", "/api/tools", params={"names": n, "view": "model"}):
                            self._full[t["name"]] = (now, t)
                    except HubCallError:
                        self._full.pop(n, None)
        return [self._full[n][1] for n in names if n in self._full]

    async def search(self, q: str) -> list[dict[str, Any]]:
        return await self._json("GET", "/api/tools", params={"q": q, "view": "model"})

    async def call(self, name: str, arguments: dict[str, Any], origin: dict[str, Any], mode: str, wait: float = 20) -> dict[str, Any]:
        try:
            return await self._json("POST", f"/api/tools/{name}/call", params={"wait": wait},
                                    json={"arguments": arguments, "origin": origin, "mode": mode})
        except HubCallError as e:
            return {"status": "error", "tool": name, "error": {"code": e.code, "detail": e.detail}}

    async def call_status(self, call_id: str, wait: float = 20) -> dict[str, Any]:
        return await self._json("GET", f"/api/tools/calls/{call_id}", params={"wait": wait})

    async def cancel_call(self, call_id: str) -> dict[str, Any]:
        return await self._json("POST", f"/api/tools/calls/{call_id}/cancel")

    async def call_result(self, call_id: str, offset: int, limit: int) -> dict[str, Any]:
        return await self._json("GET", f"/api/tools/calls/{call_id}/result", params={"offset": offset, "limit": limit})

    async def approval(self, aid: str) -> dict[str, Any]:
        return await self._json("GET", f"/api/approvals/{aid}")

    async def decide(self, aid: str, approve: bool, arguments: dict[str, Any] | None, reason: str | None) -> dict[str, Any]:
        return await self._json("POST", f"/api/approvals/{aid}", params={"wait": 0},
                                json={"approve": approve, "arguments": arguments, "reason": reason})

    # ---- outputs, services, skills -----------------------------------------------------------

    async def output(self, oid: str) -> dict[str, Any]:
        return await self._json("GET", f"/api/outputs/{oid}")

    async def output_bytes(self, oid: str, preview: bool = False) -> tuple[bytes, str]:
        r = await self.client.get(f"/api/outputs/{oid}/{'preview' if preview else 'file'}")
        if r.status_code >= 400:
            raise HubCallError(r.status_code, "not_found", f"output {oid}: HTTP {r.status_code}")
        return r.content, r.headers.get("content-type", "")

    async def output_file(self, oid: str, path: str) -> tuple[bytes, str]:
        r = await self.client.get(f"/api/outputs/{oid}/files/{path}")
        if r.status_code >= 400:
            raise HubCallError(r.status_code, "not_found", f"output {oid}/{path}: HTTP {r.status_code}")
        return r.content, r.headers.get("content-type", "")

    async def services(self) -> list[dict[str, Any]]:
        return await self._json("GET", "/api/services")

    async def memory(self) -> dict[str, Any]:
        return await self._json("GET", "/api/memory")

    async def skills(self) -> list[dict[str, Any]]:
        try:
            return await self._json("GET", "/api/skills")
        except (HubCallError, httpx.HTTPError):
            return []

    async def skill(self, mod: str, name: str) -> dict[str, Any]:
        return await self._json("GET", f"/api/skills/{mod}/{name}")

    # ---- events ------------------------------------------------------------------------------

    async def follow_events(self, on_event: Callable[[dict[str, Any]], Awaitable[None]], stop: asyncio.Event) -> None:
        """Follow `/api/events` until `stop`, reconnecting with a back-off."""
        delay = 1.0
        while not stop.is_set():
            try:
                async with self.client.stream("GET", "/api/events", timeout=httpx.Timeout(None, connect=5)) as r:
                    delay = 1.0
                    async for line in r.aiter_lines():
                        if stop.is_set():
                            return
                        if line.startswith("data:"):
                            try:
                                ev = json.loads(line[5:].strip())
                            except ValueError:
                                continue
                            try:
                                await on_event(ev)
                            except Exception:  # noqa: BLE001
                                log.exception("hub event handler")
            except (httpx.HTTPError, OSError):
                pass
            try:
                await asyncio.wait_for(stop.wait(), timeout=delay)
            except asyncio.TimeoutError:
                pass
            delay = min(delay * 2, 30)


class HubCallError(Exception):
    def __init__(self, status: int, code: str, detail: str, data: Any = None) -> None:
        super().__init__(detail)
        self.status, self.code, self.detail, self.data = status, code, detail, data
