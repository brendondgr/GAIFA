"""Mod dashboard widgets (architecture §13, brief §11.7): each `[[ui.widgets]]` of a running mod,
and its data fetched from the mod's `source` route, validated and cached for 30 s."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

import httpx

from utils.services.check import widget_problems
from utils.services.model import ServiceError

if TYPE_CHECKING:
    from utils.services import ServiceManager

CACHE_S = 30.0
TIMEOUT_S = 10.0
DEFAULT_RANGE = "24h"
LIVE = ("ready", "degraded")


class Widgets:
    def __init__(self, services: ServiceManager, clock: Any = time.monotonic) -> None:
        self.mgr = services
        self.clock = clock
        self._cache: dict[tuple[str, str, str], tuple[float, dict[str, Any]]] = {}

    def list(self) -> list[dict[str, Any]]:
        out = []
        for svc in self.mgr.list():
            if svc.state not in LIVE or not svc.m:
                continue
            for w in svc.m.ui.widgets:
                out.append({"service": svc.id, "id": w.id, "title": w.title, "kind": w.kind,
                            "ranges": list(w.ranges), "span": w.span})
        return out

    async def get(self, service_id: str, widget_id: str, rng: str | None) -> dict[str, Any]:
        svc = self.mgr.get(service_id)
        w = next((x for x in (svc.m.ui.widgets if svc.m else []) if x.id == widget_id), None)
        if w is None:
            raise ServiceError(404, "widget_not_found", f"{svc.mod.name} has no widget {widget_id!r}")
        rng = rng or (w.ranges[0] if w.ranges else DEFAULT_RANGE)
        if w.ranges and rng not in w.ranges:
            raise ServiceError(422, "invalid_request", f"range {rng!r}: {w.title} offers {', '.join(w.ranges)}")
        if svc.state not in LIVE:
            raise ServiceError(503, "service_not_running", f"{svc.mod.name} is not running")
        key = (service_id, widget_id, rng)
        hit = self._cache.get(key)
        if hit and self.clock() - hit[0] < CACHE_S:
            return hit[1]
        method, path = w.source.split(" ", 1)
        try:
            r = await self.mgr.client.request(method, svc.url + path, params={"range": rng}, timeout=TIMEOUT_S)
        except httpx.HTTPError as e:
            raise ServiceError(502, "upstream_error", f"{svc.mod.name}: {w.source} failed ({type(e).__name__})") from None
        if not 200 <= r.status_code < 300:
            raise ServiceError(502, "upstream_error", f"{svc.mod.name}: {w.source}?range={rng} answered HTTP {r.status_code}",
                               {"status": r.status_code, "body": r.text[:2000]})
        try:
            data = r.json()
        except ValueError:
            raise ServiceError(502, "upstream_error", f"{svc.mod.name}: {w.source} did not return JSON") from None
        problems = widget_problems(data, w.kind)
        if problems:
            raise ServiceError(502, "widget_invalid", f"{svc.mod.name}'s {w.title} widget: {'; '.join(problems)}", {"problems": problems})
        self._cache[key] = (self.clock(), data)
        if len(self._cache) > 256:  # drop expired entries now and then
            now = self.clock()
            self._cache = {k: v for k, v in self._cache.items() if now - v[0] < CACHE_S}
        return data
