"""AIHub over HTTP: outputs (architecture §6), memory (§7) and the models registry (§8). Never hub imports."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import httpx

log = logging.getLogger("embed")
THREAD_ID = re.compile(r"t_[0-9a-f]{12}")      # the agent's thread ids (services/agent: "t_" + 6 random bytes in hex)


class HubError(Exception):
    """Passed on to the caller as `{detail, code, data?}` with this status."""

    def __init__(self, status: int, detail: str, code: str, fix: str | None = None, data: dict | None = None):
        super().__init__(detail)
        self.status, self.detail, self.code, self.fix, self.data = status, detail, code, fix, data

    def body(self) -> dict[str, Any]:
        b: dict[str, Any] = {"detail": self.detail, "code": self.code}
        if self.fix:
            b["fix"] = self.fix
        if self.data:
            b["data"] = self.data
        return b


def output_id(ref: str) -> str:
    """`output:<id>`, `<id>` or `/api/outputs/<id>[/file]` → `<id>`."""
    ref = ref.strip()
    if ref.startswith("output:"):
        return ref.split(":", 1)[1]
    if ref.startswith("/api/outputs/"):
        return ref.removeprefix("/api/outputs/").split("/", 1)[0]
    return ref


class Hub:
    def __init__(self, url: str | None, transport: httpx.AsyncBaseTransport | None = None):
        self.url = (url or "").rstrip("/") or None
        self.service = os.environ.get("AIHUB_SERVICE_ID", "embed")
        self.transport = transport

    def _client(self, read: float = 60) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self.url or "", timeout=httpx.Timeout(10, read=read), transport=self.transport)

    async def output(self, ref: str, max_bytes: int) -> tuple[dict[str, Any], bytes]:
        """An output's record and its main file's bytes."""
        if not self.url:
            raise HubError(503, "no hub to read outputs from (AIHUB_URL is unset)", "hub_unreachable")
        oid = output_id(ref)
        try:
            async with self._client(read=120) as c:
                meta = await c.get(f"/api/outputs/{oid}")
                if meta.status_code == 404:
                    raise HubError(404, f"no output {oid!r}", "output_not_found",
                                   fix="pass an id from GET /api/outputs, as output:<id>")
                meta.raise_for_status()
                rec = meta.json()
                if (rec.get("size_bytes") or 0) > max_bytes:
                    raise HubError(413, f"output {oid} is {rec['size_bytes'] / 1e6:.0f} MB; the limit is "
                                   f"{max_bytes / 1e6:.0f} MB", "too_large")
                r = await c.get(f"/api/outputs/{oid}/file")
                r.raise_for_status()
                return rec, r.content
        except httpx.HTTPStatusError as e:
            raise HubError(502, f"the hub answered {e.response.status_code} for output {oid}", "hub_error") from e
        except httpx.HTTPError as e:
            raise HubError(503, f"AIHub not reachable ({e})", "hub_unreachable") from e

    # ---- the library's reads (plan 28.2) ---------------------------------------------------

    async def _get(self, path: str, params: dict | None = None, read: float = 120) -> httpx.Response:
        if not self.url:
            raise HubError(503, "no hub (AIHUB_URL is unset)", "hub_unreachable")
        try:
            async with self._client(read=read) as c:
                r = await c.get(path, params=params)
        except httpx.HTTPError as e:
            raise HubError(503, f"AIHub not reachable ({e})", "hub_unreachable") from e
        if r.status_code == 404:
            raise HubError(404, f"not found: {path}", "not_found")
        if r.status_code >= 400:
            try:
                b = r.json()
            except ValueError:
                b = {}
            raise HubError(502 if r.status_code >= 500 else r.status_code, b.get("detail") or f"HTTP {r.status_code} for {path}",
                           b.get("code") or "hub_error")
        return r

    async def record(self, oid: str) -> dict[str, Any]:
        return (await self._get(f"/api/outputs/{oid}")).json()

    async def outputs(self, page: int = 500) -> AsyncIterator[dict[str, Any]]:
        """Every output, newest first (`GET /api/outputs`, cursor paging)."""
        cursor = None
        while True:
            body = (await self._get("/api/outputs", {"limit": page, **({"cursor": cursor} if cursor else {})})).json()
            for rec in body.get("items") or []:
                yield rec
            cursor = body.get("next_cursor")
            if not cursor:
                return

    async def text(self, oid: str, offset: int = 0, limit: int = 48_000, pages: str | None = None) -> dict[str, Any]:
        """A window of an output's text (`GET /api/outputs/{id}/text`, plan 24.3)."""
        params: dict[str, Any] = {"offset": offset, "limit": limit, **({"pages": pages} if pages else {})}
        return (await self._get(f"/api/outputs/{oid}/text", params)).json()

    async def file(self, oid: str, preview: bool = False) -> bytes:
        return (await self._get(f"/api/outputs/{oid}/{'preview' if preview else 'file'}", read=300)).content

    async def thread_attachments(self, tid: str) -> list[str]:
        """The outputs attached in a chat: the agent's `user` events (through the hub's proxy). The id goes into
        a hub path, so only the agent's own id shape is sent."""
        if not THREAD_ID.fullmatch(tid):
            raise HubError(422, f"{tid[:40]!r} isn't a chat id (t_ and 12 hex digits)", "bad_thread",
                           fix="use the thread:<id> collection that library_collections lists, or leave collection out")
        try:
            evs = (await self._get(f"/api/s/agent/v1/threads/{tid}/events")).json()
        except HubError as e:
            if e.status == 404:
                raise HubError(404, f"no chat {tid!r} (or the agent mod isn't installed)", "no_thread",
                               fix="leave thread_only out to search everything") from e
            raise
        except ValueError as e:
            raise HubError(502, f"the agent's events for {tid} weren't JSON", "hub_error") from e
        if not isinstance(evs, list):
            raise HubError(502, f"the agent's events for {tid} came as {type(evs).__name__}, not a list", "hub_error")
        out: list[str] = []
        for e in evs:
            payload = e.get("payload") if isinstance(e, dict) and e.get("type") == "user" else None
            atts = payload.get("attachments") if isinstance(payload, dict) else None
            if isinstance(atts, list):
                out += [a for a in atts if isinstance(a, str) and a not in out]
        return out

    async def follow(self, on_event: Callable[[dict[str, Any]], Awaitable[None]],
                     on_connect: Callable[[], Awaitable[None]], stop: asyncio.Event) -> None:
        """Follow `/api/events`, reconnecting with a back-off; `on_connect` runs on every (re)connect, since
        events can be missed while disconnected."""
        delay = 1.0
        while not stop.is_set() and self.url:
            try:
                async with httpx.AsyncClient(base_url=self.url, timeout=httpx.Timeout(None, connect=5),
                                             transport=self.transport) as c:
                    async with c.stream("GET", "/api/events") as r:
                        if r.status_code == 200:
                            delay = 1.0
                            await on_connect()
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
                                    except Exception:      # noqa: BLE001: one bad event never ends the follower
                                        log.exception("hub event handler")
            except (httpx.HTTPError, OSError, HubError) as e:
                log.debug("events: %s", e)
            try:
                await asyncio.wait_for(stop.wait(), timeout=delay)
            except TimeoutError:
                pass
            delay = min(delay * 2, 30)

    async def acquire(self, gb: float, reason: str) -> None:
        """Ask for memory before loading another encoder; a 409 needs_room is passed on unchanged."""
        if not self.url or gb <= 0:
            return
        try:
            async with self._client(read=180) as c:
                r = await c.post("/api/memory/acquire", json={"service": self.service, "needs_bytes": int(gb * 1e9),
                                                              "reason": reason})
        except httpx.HTTPError as e:
            log.warning("AIHub not reachable for memory (%s); loading anyway", e)
            return
        if r.status_code == 409:
            b = r.json()
            raise HubError(409, b.get("detail") or "not enough free memory", b.get("code") or "needs_room",
                           data=b.get("data"))
        if r.status_code >= 400:
            log.warning("memory acquire answered %s: %s", r.status_code, r.text[:200])

    async def register_model(self, entry: dict[str, Any]) -> str:
        """POST /api/models; an existing entry (409 model_exists) is fine."""
        if not self.url:
            return "no hub"
        try:
            async with self._client() as c:
                r = await c.post("/api/models", json=entry)
        except httpx.HTTPError as e:
            return f"AIHub not reachable ({e})"
        if r.status_code < 300:
            return "registered"
        if r.status_code == 409:
            return "exists"
        return f"HTTP {r.status_code}: {r.text[:200]}"
