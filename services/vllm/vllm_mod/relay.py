"""Publishing the running engine to the relay (`/admin/registrations`, plan 18.4), the way lcpp
publishes its llama.cpp servers (services/lcpp/src/lcpp/relay.py; written again here, since mods
don't import each other).

The engine is registered as `vllm:<engine port>` once it is ready, and removed when an unload starts
and again once it is gone. Every call is idempotent on the relay side. A relay that is down leaves
the registration (or the removal) pending, and one retry loop with capped backoff works through it;
there is no polling otherwise. On adapter start, `reconcile` removes registrations of ours with no
engine behind them.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

import httpx

from .profiles import Profile
from .settings import Settings

log = logging.getLogger("vllm")
OWNER = "vllm"
RETRY_DELAYS = (1.0, 2.0, 5.0, 10.0, 30.0, 60.0)


class Relay:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None,
                 delays: tuple[float, ...] = RETRY_DELAYS):
        self.s = settings
        self.key = f"{OWNER}:{settings.engine_port}"
        self.http = httpx.AsyncClient(base_url=settings.relay_url, timeout=httpx.Timeout(20, connect=2),
                                      transport=transport)
        self.delays = delays
        self.state = "off"            # off | pending | registered | error
        self.error: str | None = None
        self.alias: str | None = None
        self.skipped: list[str] = []
        self._want: Profile | None = None       # what should be registered (None: nothing)
        self._delete = False                   # a removal still to send
        self._retry: asyncio.Task | None = None

    def body(self, p: Profile) -> dict[str, Any]:
        hub = os.environ.get("GAIFA_URL", "http://127.0.0.1:7000").rstrip("/")
        return {"name": f"vllm-{p.id}", "port": self.s.engine_port, "host": "127.0.0.1", "alias": p.alias,
                "available_models": [p.served], "server_type": "vLLM", "owner": OWNER,
                "meta": {"manager_url": f"{hub}/#/s/vllm", "profile": p.id, "model": p.model,
                         "registered_ts": time.time()}}

    # engine hooks -------------------------------------------------------------------------------

    async def publish(self, p: Profile) -> None:
        self._want, self._delete = p, False
        await self._put(p)

    async def withdraw(self, p: Profile | None = None) -> None:
        self._want, self._delete = None, True
        await self._del()

    # calls ------------------------------------------------------------------------------------

    async def _put(self, p: Profile) -> bool:
        try:
            r = await self.http.put(f"/admin/registrations/{self.key}", json=self.body(p))
        except httpx.HTTPError as e:
            return self._pending(f"relay unreachable ({type(e).__name__})")
        if r.status_code >= 500:
            return self._pending(f"relay answered HTTP {r.status_code}")
        if r.status_code >= 400:
            try:
                detail = r.json().get("detail") or r.text
            except ValueError:
                detail = r.text
            self.state, self.error = "error", str(detail)
            log.warning("the relay rejected the registration: %s", detail)
            return True
        reg = r.json()
        self.state, self.error = "registered", None
        ep = reg.get("endpoint") or {}
        self.alias = ep.get("alias") or p.alias
        await self._facts(p, ep)
        self.skipped = reg.get("skipped_models") or []
        if self.skipped:
            log.info("the relay already routes %s elsewhere; reachable by alias", ", ".join(self.skipped))
        log.info("published %s to the relay as %s", p.served, self.key)
        return True

    async def _facts(self, p: Profile, ep: dict[str, Any]) -> None:
        """vLLM's /v1/models gives the context window but not whether tool calls and thinking are
        parsed; the profile knows (plan 13.3's facts_override, set on the endpoint)."""
        want = {"tools": True if p.tool_parser else None, "reasoning": True if p.reasoning_parser else None}
        want = {k: v for k, v in want.items() if v is not None}
        have = {k: v for k, v in (ep.get("facts_override") or {}).items() if v is not None}
        if not ep.get("id") or want == have:
            return
        try:
            r = await self.http.patch(f"/admin/endpoints/{ep['id']}", json={"facts_override": want or None})
            if r.status_code >= 400:
                log.warning("the relay refused the model facts: HTTP %s %s", r.status_code, r.text[:200])
        except httpx.HTTPError as e:
            log.warning("model facts not sent (%s)", type(e).__name__)

    async def _del(self) -> bool:
        try:
            r = await self.http.delete(f"/admin/registrations/{self.key}")
            if r.status_code < 500:
                self._delete = False
                self.state, self.error, self.alias, self.skipped = "off", None, None, []
                return True
            why = f"relay answered HTTP {r.status_code}"
        except httpx.HTTPError as e:
            why = f"relay unreachable ({type(e).__name__})"
        return self._pending(why)

    def _pending(self, why: str) -> bool:
        self.state, self.error = "pending", why
        if self._retry is None or self._retry.done():
            self._retry = asyncio.create_task(self._retry_loop())
        return False

    async def _retry_loop(self) -> None:
        i = 0
        while True:
            await asyncio.sleep(self.delays[min(i, len(self.delays) - 1)])
            i += 1
            if self._delete:
                ok = await self._del()
            elif self._want is not None:
                ok = await self._put(self._want)
            else:
                return
            if ok:
                return

    async def reconcile(self, ready: Profile | None) -> None:
        """Adapter start: remove registrations of ours that nothing serves; publish the adopted engine
        (the engine's on_ready hook does that once it is healthy)."""
        try:
            r = await self.http.get("/admin/registrations", params={"owner": OWNER})
            r.raise_for_status()
            regs = r.json()
        except (httpx.HTTPError, ValueError) as e:
            log.info("relay not reachable at start (%s)", type(e).__name__)
            return
        for reg in regs:
            if reg.get("key") != self.key or ready is None:
                await self.http.delete(f"/admin/registrations/{reg.get('key')}")
                log.info("removed the stale relay registration %s", reg.get("key"))

    async def close(self) -> None:
        if self._retry:
            self._retry.cancel()
        await self.http.aclose()

    def view(self) -> dict[str, Any]:
        return {"key": self.key, "url": self.s.relay_url, "state": self.state, "error": self.error,
                "alias": self.alias, "skipped_models": self.skipped}
