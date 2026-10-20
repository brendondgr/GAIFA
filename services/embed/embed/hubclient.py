"""AIHub over HTTP: outputs (architecture §6), memory (§7) and the models registry (§8). Never hub imports."""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

log = logging.getLogger("embed")


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
