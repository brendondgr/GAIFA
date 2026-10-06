"""Publishing instances to the DashLLM relay (``/admin/registrations``).

Each instance with relay enabled is registered as ``lcpp:<port>`` once it is
ready, and removed when it starts stopping (so the relay stops routing to it
before the process goes away) and again when it is gone (covers crashes).
Every call is idempotent on the relay side, so repeating one is always safe.

The relay may be down or restarting at any of those moments. Registrations
then go ``pending`` (and deletions are queued), and a single retry loop with
capped backoff works through them. The loop exists only while something is
pending; there is no background polling otherwise.

On daemon start, ``reconcile`` makes the relay match reality: registrations
owned by lcpp with no running instance are removed, and running instances are
re-registered. Relay-side drift (someone deleting our endpoint in the
dashboard, a wiped relay DB) is healed the same way whenever the owned list is
fetched.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any

import httpx

from lcpp import aihub
from lcpp import settings as settings_mod
from lcpp.instances import Instance, LcppError

if TYPE_CHECKING:
    from lcpp.daemon.app import State

log = logging.getLogger("lcpp.relay")

OWNER = settings_mod.RELAY_OWNER
STATUS_TTL_S = 5.0
RETRY_DELAYS = (1.0, 2.0, 5.0, 10.0, 30.0, 60.0)


def key_for(port: int) -> str:
    return f"{OWNER}:{port}"


class RelayRegistrar:
    def __init__(self, st: "State"):
        self.st = st
        self.http: httpx.AsyncClient | None = None
        self._status: dict[str, Any] | None = None
        self._owned: list[dict[str, Any]] | None = None
        self._checked = 0.0
        self._pending_deletes: set[str] = set()
        self._retry: asyncio.Task[None] | None = None

    @property
    def url(self) -> str:
        return self.st.settings["relay"]["url"]

    @property
    def sup(self):
        return self.st.supervisor

    # ---- lifecycle ------------------------------------------------------------
    async def start(self) -> None:
        self.http = httpx.AsyncClient(timeout=httpx.Timeout(5.0, connect=1.0))

    async def close(self) -> None:
        if self._retry:
            self._retry.cancel()
            await asyncio.gather(self._retry, return_exceptions=True)
        if self.http:
            await self.http.aclose()

    async def settings_changed(self) -> None:
        await self.reconcile()

    # ---- reachability -----------------------------------------------------------
    async def status(self, fresh: bool = False) -> dict[str, Any]:
        """Reachability (and lcpp's registrations), cached briefly so UI polling
        never hammers the relay."""
        if not fresh and self._status and time.monotonic() - self._checked < STATUS_TTL_S:
            return self._status
        assert self.http is not None
        t0 = time.monotonic()
        err = None
        try:
            r = await self.http.get(f"{self.url}/health")
            reachable = r.status_code < 500
            if not reachable:
                err = f"HTTP {r.status_code}"
        except httpx.HTTPError as e:
            reachable = False
            err = f"{e.__class__.__name__}: {e}" if str(e) else e.__class__.__name__
        self._status = {
            "url": self.url, "dashboard_url": self.st.settings["relay"]["dashboard_url"],
            "reachable": reachable,
            "latency_ms": round((time.monotonic() - t0) * 1000) if reachable else None,
            "error": err,
        }
        self._checked = time.monotonic()
        was = self.sup.relay_reachable
        self.sup.relay_reachable = reachable
        if reachable:
            await self._refresh_owned()
            if was is False:
                self._kick()  # it came back: flush anything pending
        else:
            self._owned = None
            self._mark_unreachable()
        return self._status

    def _mark_unreachable(self) -> None:
        for inst in self.sup.instances.values():
            if inst.relay.get("enabled") and inst.relay.get("state") == "registered":
                inst.relay.update(state="pending", health=None)
                self.sup.save(inst)
        if any(i.relay.get("state") == "pending" for i in self.sup.instances.values()):
            self._kick()

    async def _refresh_owned(self) -> None:
        """Fetch lcpp's registrations; sync health into instances and heal drift."""
        assert self.http is not None
        try:
            r = await self.http.get(f"{self.url}/admin/registrations", params={"owner": OWNER})
            r.raise_for_status()
            self._owned = r.json()
        except (httpx.HTTPError, ValueError):
            self._owned = None
            return
        by_key = {reg["key"]: reg for reg in self._owned}
        for inst in list(self.sup.instances.values()):
            rel = inst.relay
            if not rel.get("enabled") or inst.state != "ready":
                continue
            reg = by_key.get(rel.get("key") or "")
            if reg is None and rel.get("state") == "registered":
                log.warning("registration %s vanished from relay; re-registering", rel.get("key"))
                rel["state"] = "pending"
                self._kick()
            elif reg is not None:
                health = reg["endpoint"].get("health")
                if rel.get("health") != health:
                    rel["health"] = health
                    self.sup.save(inst)

    # ---- register / unregister ------------------------------------------------------
    def _body(self, inst: Instance) -> dict[str, Any]:
        cat = self.st.catalog
        if inst.kind == "single" and inst.model_id:
            entry = cat.get(inst.model_id)
            models = entry.names if entry else [inst.model_id]
        else:
            # A dedicated instance wins its model's name over a router: a
            # router only advertises models no published single instance serves.
            dedicated = {i.model_id for i in self._published_singles()}
            models = [m for m in inst.model_ids if m not in dedicated]
        return {
            "name": inst.name, "port": inst.port, "host": settings_mod.HOST,
            "alias": inst.relay.get("alias"), "available_models": models,
            "server_type": "llama.cpp", "owner": OWNER,
            "meta": {"manager_url": aihub.page_url() or settings_mod.daemon_url(self.st.settings) + "/",
                     "instance": inst.name, "registered_ts": time.time()},
        }

    def _published_singles(self) -> list[Instance]:
        return [i for i in self.sup.instances.values()
                if i.kind == "single" and i.relay.get("enabled") and i.state in ("starting", "ready")]

    async def _refresh_routers(self) -> None:
        """Re-register published routers so their model lists track which
        models currently have a dedicated instance."""
        for inst in list(self.sup.instances.values()):
            if inst.kind == "router" and inst.relay.get("state") == "registered" and inst.state == "ready":
                await self.register(inst)

    async def register(self, inst: Instance) -> None:
        """PUT the registration. Sets relay.state; never raises."""
        rel = inst.relay
        if not rel.get("enabled") or inst.state != "ready":
            return
        rel["key"] = key_for(inst.port)
        assert self.http is not None
        try:
            r = await self.http.put(f"{self.url}/admin/registrations/{rel['key']}",
                                    json=self._body(inst), timeout=20.0)
        except httpx.HTTPError as e:
            rel.update(state="pending", health=None, error=f"relay unreachable ({e.__class__.__name__})")
            self.sup.save(inst)
            self._kick()
            return
        if r.status_code >= 500:
            rel.update(state="pending", health=None, error=f"relay answered HTTP {r.status_code}")
            self.sup.save(inst)
            self._kick()
            return
        if r.status_code >= 400:
            try:
                detail = r.json().get("detail") or r.text
            except ValueError:
                detail = r.text
            rel.update(state="error", health=None, error=str(detail))
            self.sup.save(inst)
            log.warning("relay rejected %s: %s", inst.name, detail)
            return
        reg = r.json()
        ep = reg["endpoint"]
        # Adoption keeps the relay endpoint's own alias; reflect what routes.
        rel.update(state="registered", alias=ep.get("alias") or rel.get("alias"),
                   health=ep.get("health"), error=None)
        if reg.get("skipped_models"):
            log.info("%s: relay already routes %s elsewhere; reachable by alias", inst.name,
                     ", ".join(reg["skipped_models"]))
        self.sup.save(inst)
        self._owned = None  # stale now

    async def unregister(self, key: str | None) -> bool:
        """DELETE the registration; queue it for retry when relay is down."""
        if not key:
            return True
        assert self.http is not None
        try:
            r = await self.http.delete(f"{self.url}/admin/registrations/{key}")
            if r.status_code < 500:
                self._pending_deletes.discard(key)
                self._owned = None
                return True
        except httpx.HTTPError:
            pass
        self._pending_deletes.add(key)
        self._kick()
        return False

    # ---- supervisor hooks ------------------------------------------------------------
    async def instance_ready(self, inst: Instance) -> None:
        if inst.kind == "single" and inst.relay.get("enabled"):
            await self._refresh_routers()  # free the model's name first
        await self.register(inst)

    async def instance_stopping(self, inst: Instance) -> None:
        if inst.relay.get("enabled") and inst.relay.get("key"):
            await self.unregister(inst.relay["key"])

    async def instance_gone(self, inst: Instance) -> None:
        rel = inst.relay
        if not rel.get("enabled"):
            return
        await self.unregister(rel.get("key"))
        if inst.kind == "single":
            await self._refresh_routers()  # a router may serve the name again
        if inst.state == "failed":
            rel.update(state="error", health=None,
                       error="instance never became ready" if not inst.ready_ts else "instance is not running")
            self.sup.save(inst)

    # ---- retry ------------------------------------------------------------------------
    def _kick(self) -> None:
        if self._retry is None or self._retry.done():
            self._retry = asyncio.create_task(self._retry_loop())

    def _has_pending(self) -> bool:
        return bool(self._pending_deletes) or any(
            i.relay.get("enabled") and i.relay.get("state") == "pending" and i.state == "ready"
            for i in self.sup.instances.values())

    async def _retry_loop(self) -> None:
        attempt = 0
        while self._has_pending():
            await asyncio.sleep(RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)])
            attempt += 1
            status = await self.status(fresh=True)
            if not status["reachable"]:
                continue
            for key in list(self._pending_deletes):
                await self.unregister(key)
            for inst in list(self.sup.instances.values()):
                if inst.relay.get("enabled") and inst.relay.get("state") == "pending" and inst.state == "ready":
                    await self.register(inst)

    # ---- reconcile ------------------------------------------------------------------------
    async def reconcile(self) -> None:
        """Make the relay match the running instances (daemon start, settings change)."""
        status = await self.status(fresh=True)
        if not status["reachable"]:
            return
        wanted = {i.relay["key"] for i in self.sup.instances.values()
                  if i.relay.get("enabled") and i.state == "ready" and i.relay.get("key")}
        for reg in self._owned or []:
            if reg["key"] not in wanted:
                await self.unregister(reg["key"])
        # Routers first: their lists already exclude dedicated models, which
        # frees those names for the single instances registered after them.
        ordered = sorted(self.sup.instances.values(), key=lambda i: i.kind == "single")
        for inst in ordered:
            if inst.relay.get("enabled") and inst.state == "ready":
                await self.register(inst)
        self._owned = None

    # ---- UI / CLI operations ----------------------------------------------------------------
    async def publish(self, target: str, alias: str | None) -> Instance:
        inst = self.sup.get(target)
        if inst.state == "failed":
            raise LcppError("instance_not_found", f"{inst.name} is not running", 409)
        entry = self.st.catalog.get(inst.model_id) if inst.model_id else None
        alias = (alias or "").strip() or inst.relay.get("alias") or (entry.nick if entry else inst.name)
        previous = dict(inst.relay)
        if previous.get("state") == "registered" and previous.get("alias") != alias:
            await self.unregister(previous.get("key"))
        inst.relay = {"enabled": True, "state": "pending", "key": key_for(inst.port),
                      "alias": alias, "health": None, "error": None}
        inst.spec["relay"] = {"enabled": True, "alias": alias}
        self.sup.save(inst)
        if inst.state == "ready":
            if inst.kind == "single":
                await self._refresh_routers()
            await self.register(inst)
            if inst.relay["state"] == "error" and "already" in (inst.relay.get("error") or ""):
                err = inst.relay["error"]
                inst.relay = previous
                self.sup.save(inst)
                raise LcppError("alias_conflict", f"Alias \"{alias}\" is already used on Relay: {err}", 409)
        return inst

    async def unpublish(self, target: str) -> Instance:
        inst = self.sup.get(target)
        key = inst.relay.get("key")
        if key and inst.relay.get("state") in ("registered", "pending"):
            assert self.http is not None
            try:
                r = await self.http.delete(f"{self.url}/admin/registrations/{key}")
                if r.status_code >= 500:
                    raise httpx.HTTPStatusError("relay error", request=r.request, response=r)
            except httpx.HTTPError as e:
                if inst.relay.get("state") == "registered":
                    raise LcppError("relay_unreachable",
                                    "Relay unreachable: registration could not be removed", 502) from e
        self._pending_deletes.discard(key or "")
        inst.relay = {"enabled": False, "state": "off", "key": None, "alias": None,
                      "health": None, "error": None}
        inst.spec["relay"] = {"enabled": False, "alias": None}
        self.sup.save(inst)
        self._owned = None
        if inst.kind == "single":
            await self._refresh_routers()
        return inst

    async def overview(self) -> dict[str, Any]:
        status = await self.status(fresh=True)
        if not status["reachable"]:
            return {"status": status, "owned": [], "others": [], "routable_models": []}
        assert self.http is not None
        if self._owned is None:
            await self._refresh_owned()
        by_key = {i.relay.get("key"): i for i in self.sup.instances.values()
                  if i.relay.get("enabled") and i.state != "failed"}
        owned = []
        for reg in self._owned or []:
            ep = reg["endpoint"]
            inst = by_key.get(reg["key"])
            meta = ep.get("meta") or {}
            owned.append({
                "key": reg["key"], "instance": inst.name if inst else meta.get("instance"),
                "alias": ep.get("alias"), "models": ep.get("available_models") or [],
                "health": ep.get("health") or "unknown",
                "registered_ts": meta.get("registered_ts") or 0,
                "orphan": inst is None, "endpoint_id": ep["id"],
            })
        others: list[dict[str, Any]] = []
        routable: list[str] = []
        try:
            eps = (await self.http.get(f"{self.url}/admin/endpoints")).json()
            others = [{"name": e["name"], "alias": e.get("alias"), "server_type": e.get("server_type"),
                       "health": e.get("health") or "unknown", "base_url": e["base_url"]}
                      for e in eps if e.get("owner") != OWNER]
            models = (await self.http.get(f"{self.url}/v1/models")).json()
            # An alias can equal a model id (MiniCPM5-2B is both); list each name once.
            routable = list(dict.fromkeys(m["id"] for m in models.get("data", []) if m.get("id") != "auto"))
        except (httpx.HTTPError, ValueError, KeyError):
            pass
        return {"status": status, "owned": owned, "others": others, "routable_models": routable}

    async def remove_registration(self, key: str) -> None:
        await self.unregister(key)
        for inst in self.sup.instances.values():
            if inst.relay.get("key") == key:
                inst.relay = {"enabled": False, "state": "off", "key": None, "alias": None,
                              "health": None, "error": None}
                inst.spec["relay"] = {"enabled": False, "alias": None}
                self.sup.save(inst)

    async def cleanup_orphans(self) -> list[str]:
        data = await self.overview()
        removed = []
        for reg in data["owned"]:
            if reg["orphan"]:
                await self.unregister(reg["key"])
                removed.append(reg["key"])
        return removed
