"""Talking to the DashLLM relay.

At this stage only reachability is tracked; registration arrives with the
relay's registration API.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

import httpx

from lcpp.instances import Instance

if TYPE_CHECKING:
    from lcpp.daemon.app import State

STATUS_TTL_S = 5.0


class RelayRegistrar:
    def __init__(self, st: "State"):
        self.st = st
        self.http: httpx.AsyncClient | None = None
        self._status: dict[str, Any] | None = None
        self._checked = 0.0

    @property
    def url(self) -> str:
        return self.st.settings["relay"]["url"]

    async def start(self) -> None:
        self.http = httpx.AsyncClient(timeout=httpx.Timeout(3.0, connect=1.0))

    async def close(self) -> None:
        if self.http:
            await self.http.aclose()

    async def reconcile(self) -> None:
        await self.status(fresh=True)

    async def settings_changed(self) -> None:
        await self.status(fresh=True)

    async def status(self, fresh: bool = False) -> dict[str, Any]:
        """Reachability, cached briefly so UI polling never hammers the relay."""
        if not fresh and self._status and time.monotonic() - self._checked < STATUS_TTL_S:
            return self._status
        assert self.http is not None
        t0 = time.monotonic()
        try:
            r = await self.http.get(f"{self.url}/health")
            reachable, err = r.status_code < 500, None if r.status_code < 500 else f"HTTP {r.status_code}"
        except httpx.HTTPError as e:
            reachable, err = False, f"{e.__class__.__name__}: {e}" if str(e) else e.__class__.__name__
        self._status = {
            "url": self.url, "dashboard_url": self.st.settings["relay"]["dashboard_url"],
            "reachable": reachable, "latency_ms": round((time.monotonic() - t0) * 1000) if reachable else None,
            "error": err,
        }
        self._checked = time.monotonic()
        self.st.supervisor.relay_reachable = reachable
        return self._status

    async def overview(self) -> dict[str, Any]:
        return {"status": await self.status(), "owned": [], "others": [], "routable_models": []}

    # ---- supervisor hooks -------------------------------------------------
    async def instance_ready(self, inst: Instance) -> None:
        pass

    async def instance_stopping(self, inst: Instance) -> None:
        pass

    async def instance_gone(self, inst: Instance) -> None:
        pass
