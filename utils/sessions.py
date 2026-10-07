"""Sessions (plan Phase 15): named snapshots of what runs and what's loaded, restored through the
memory manager.

A snapshot holds each mod's running and load state and lcpp's instances with their launch specs
(`GET /api/s/lcpp/api/instances`). Restoring makes a plan first (`dry_run` returns only the plan):

1. stop lcpp instances the session doesn't have (LLMs are never unloaded automatically)
2. unload mods that are loaded now but not in the session
3. start mods the session runs
4. launch the session's lcpp instances that aren't running
5. load the session's loaded mods (each through the memory manager, which makes room)

Mods that run now but not in the session keep running (processes are cheap; models aren't).
An `auto` session ("Last session") is saved every `sessions.autosave_s` and at a clean shutdown.
At startup the previous run's "Last session" is first copied to "Before restart", which the
auto-save never touches: after a reboot the auto-save would otherwise replace the setup worth
restoring with the bare state the machine booted into. `sessions.restore_on_boot` and the
unclean-shutdown offer both use "Before restart".
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import time
from typing import TYPE_CHECKING, Any

import httpx

from utils.services import loading

if TYPE_CHECKING:
    from utils.server import Hub

log = logging.getLogger("aihub.sessions")
AUTO_NAME = "Last session"
BOOT_NAME = "Before restart"     # the previous run's last setup, kept at startup
GB = 1e9
CLEAN_KEY = "sessions:clean_shutdown"


class SessionError(Exception):
    def __init__(self, status: int, code: str, detail: str) -> None:
        super().__init__(detail)
        self.status, self.code, self.detail = status, code, detail


def _row(r: dict[str, Any]) -> dict[str, Any]:
    s = json.loads(r["snapshot"])
    return {"id": r["id"], "name": r["name"], "auto": bool(r["auto"]), "created_ts": r["created_ts"], "updated_ts": r["updated_ts"],
            "snapshot": s, "summary": summary(s)}


def summary(s: dict[str, Any]) -> str:
    loaded = [m for m, v in s.get("mods", {}).items() if v.get("load") == "loaded"]
    llms = [i.get("relay", {}).get("alias") or i.get("model_id") or i.get("name") for i in s.get("lcpp", [])]
    parts = []
    if llms:
        parts.append("LLMs: " + ", ".join(str(x) for x in llms))
    if loaded:
        parts.append("loaded: " + ", ".join(loaded))
    running = [m for m, v in s.get("mods", {}).items() if v.get("running")]
    parts.append(f"{len(running)} mods running")
    return "; ".join(parts)


class Sessions:
    def __init__(self, hub: Hub) -> None:
        self.hub = hub
        self.client = httpx.AsyncClient(trust_env=False, timeout=httpx.Timeout(600, connect=5))
        self._task: asyncio.Task[Any] | None = None
        self.unclean_previous = False
        self.restoring: str | None = None

    # ---- lifecycle ---------------------------------------------------------------------------

    async def start(self) -> None:
        row = await self.hub.db.fetchone("SELECT value FROM kv WHERE key = ?", (CLEAN_KEY,))
        self.unclean_previous = row is not None and row["value"] == "0"
        await self._kv(CLEAN_KEY, "0")
        await self._keep_previous()
        every = self.hub.config.sessions.autosave_s
        if every:
            self._task = asyncio.create_task(self._autosave(every))
        if self.hub.config.sessions.restore_on_boot:
            asyncio.create_task(self._restore_on_boot())

    async def close(self) -> None:
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        try:
            if self.hub.config.sessions.autosave_s:
                await self.save(AUTO_NAME, auto=True)
            await self._kv(CLEAN_KEY, "1")
        except Exception:  # noqa: BLE001
            log.exception("saving the last session at shutdown")
        await self.client.aclose()

    async def _kv(self, key: str, value: str) -> None:
        await self.hub.db.execute("INSERT INTO kv (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                                  (key, value))

    async def _keep_previous(self) -> None:
        """Copy the previous run's "Last session" to "Before restart" (its save time kept)."""
        last = await self.hub.db.fetchone("SELECT snapshot, updated_ts FROM sessions WHERE name = ? AND auto = 1", (AUTO_NAME,))
        if last is None:
            return
        old = await self.hub.db.fetchone("SELECT id FROM sessions WHERE name = ?", (BOOT_NAME,))
        if old:
            await self.hub.db.execute("UPDATE sessions SET snapshot = ?, updated_ts = ?, auto = 1 WHERE id = ?",
                                      (last["snapshot"], last["updated_ts"], old["id"]))
        else:
            await self.hub.db.execute("INSERT INTO sessions (id, name, auto, snapshot, created_ts, updated_ts) VALUES (?, ?, 1, ?, ?, ?)",
                                      ("ss_" + secrets.token_hex(5), BOOT_NAME, last["snapshot"], last["updated_ts"], last["updated_ts"]))

    async def before_restart(self) -> dict[str, Any] | None:
        row = await self.hub.db.fetchone("SELECT * FROM sessions WHERE name = ? AND auto = 1", (BOOT_NAME,))
        return _row(row) if row else None

    async def _autosave(self, every: float) -> None:
        while True:
            await asyncio.sleep(every)
            try:
                await self.save(AUTO_NAME, auto=True)
            except Exception:  # noqa: BLE001
                log.exception("auto-save")

    async def _restore_on_boot(self) -> None:
        await asyncio.sleep(5)    # let autostart finish first
        row = await self.hub.db.fetchone("SELECT * FROM sessions WHERE name = ? AND auto = 1", (BOOT_NAME,))
        if row:
            log.info("restoring %s at boot", row["name"])
            try:
                await self.restore(row["id"])
            except Exception:  # noqa: BLE001
                log.exception("restore at boot")

    # ---- snapshots ---------------------------------------------------------------------------

    async def snapshot(self) -> dict[str, Any]:
        mods = {}
        for s in self.hub.services.list():
            mods[s.id] = {"running": s.up, "load": s.load}
        lcpp: list[dict[str, Any]] = []
        notes: list[str] = []
        try:
            svc = self.hub.services.get("lcpp")
            if svc.up:
                r = await self.client.get(f"{svc.url}/api/instances", timeout=10)
                r.raise_for_status()
                for i in r.json():
                    if i.get("state") not in ("ready", "starting", "loading"):
                        continue
                    relay = i.get("relay") or {}
                    lcpp.append({"name": i["name"], "kind": i.get("kind", "single"), "model_id": i.get("model_id"),
                                 "model_ids": i.get("models") and [m.get("id") if isinstance(m, dict) else m for m in i["models"]] or [],
                                 "port": i.get("port"), "params": i.get("params") or {},
                                 "relay": {"enabled": relay.get("state") not in (None, "off"), "alias": relay.get("alias")},
                                 "rss_bytes": i.get("rss_bytes") or 0})
        except Exception as e:  # noqa: BLE001
            notes.append(f"lcpp instances not read: {e}")
        return {"version": 1, "ts": time.time(), "mods": mods, "lcpp": lcpp, "notes": notes}

    async def list(self) -> list[dict[str, Any]]:
        return [_row(r) for r in await self.hub.db.fetchall("SELECT * FROM sessions ORDER BY auto, updated_ts DESC")]

    async def get(self, sid: str) -> dict[str, Any]:
        r = await self.hub.db.fetchone("SELECT * FROM sessions WHERE id = ? OR name = ?", (sid, sid))
        if r is None:
            raise SessionError(404, "not_found", f"no session {sid!r}")
        return _row(r)

    async def save(self, name: str, auto: bool = False, snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
        name = name.strip()
        if not name or len(name) > 80:
            raise SessionError(422, "invalid_request", "name: 1–80 characters")
        snap = snapshot or await self.snapshot()
        now = time.time()
        existing = await self.hub.db.fetchone("SELECT id, auto FROM sessions WHERE name = ?", (name,))
        if existing:
            await self.hub.db.execute("UPDATE sessions SET snapshot = ?, updated_ts = ? WHERE id = ?", (json.dumps(snap), now, existing["id"]))
            sid = existing["id"]
        else:
            sid = "ss_" + secrets.token_hex(5)
            await self.hub.db.execute("INSERT INTO sessions (id, name, auto, snapshot, created_ts, updated_ts) VALUES (?, ?, ?, ?, ?, ?)",
                                      (sid, name, int(auto), json.dumps(snap), now, now))
        s = await self.get(sid)
        if not auto:
            self.hub.bus.publish({"type": "session", "session": {k: v for k, v in s.items() if k != "snapshot"}})
        return s

    async def rename(self, sid: str, name: str) -> dict[str, Any]:
        s = await self.get(sid)
        if await self.hub.db.fetchone("SELECT id FROM sessions WHERE name = ? AND id != ?", (name, s["id"])):
            raise SessionError(409, "conflict", f"a session is already called {name!r}")
        await self.hub.db.execute("UPDATE sessions SET name = ?, updated_ts = ? WHERE id = ?", (name.strip(), time.time(), s["id"]))
        return await self.get(s["id"])

    async def delete(self, sid: str) -> None:
        s = await self.get(sid)
        await self.hub.db.execute("DELETE FROM sessions WHERE id = ?", (s["id"],))

    # ---- restoring ---------------------------------------------------------------------------

    async def plan(self, sid: str) -> dict[str, Any]:
        target = (await self.get(sid))["snapshot"]
        now = await self.snapshot()
        mem = self.hub.memory
        steps: list[dict[str, Any]] = []
        want_llm = {(i.get("model_id"), i.get("port")): i for i in target.get("lcpp", [])}
        have_llm = {(i.get("model_id"), i.get("port")): i for i in now.get("lcpp", [])}
        freed = needed = 0
        for key, i in have_llm.items():
            if key not in want_llm:
                steps.append({"action": "stop_llm", "target": i["name"], "detail": f"stop {i.get('relay', {}).get('alias') or i['name']}",
                              "bytes": -int(i.get("rss_bytes") or 0)})
                freed += int(i.get("rss_bytes") or 0)
        def has_op(mod: str, op: str) -> bool:
            """Mods without a load/unload operation (lcpp: its instances are its load) aren't loaded or unloaded here."""
            try:
                mm = self.hub.services.get(mod).m
            except Exception:  # noqa: BLE001
                return False
            return bool(mm and mm.memory and getattr(mm.memory, op))

        for m, v in now["mods"].items():
            t = target["mods"].get(m)
            if v["load"] == "loaded" and (t is None or t.get("load") != "loaded") and has_op(m, "unload"):
                used = mem.used.get(m, 0) if mem else 0
                steps.append({"action": "unload", "target": m, "detail": f"unload {m}", "bytes": -used})
                freed += used
        for m, t in target["mods"].items():
            cur = now["mods"].get(m)
            if cur is None:
                steps.append({"action": "skip", "target": m, "detail": f"{m} isn't installed any more"})
                continue
            if t.get("running") and not cur["running"]:
                steps.append({"action": "start", "target": m, "detail": f"start {m}"})
        for key, i in want_llm.items():
            if key not in have_llm:
                b = int(i.get("rss_bytes") or 0)
                steps.append({"action": "launch_llm", "target": i["name"], "detail": f"launch {i.get('relay', {}).get('alias') or i['name']}",
                              "bytes": b, "spec": {k: i[k] for k in ("kind", "model_id", "model_ids", "port", "params", "relay", "name")}})
                needed += b
        for m, t in target["mods"].items():
            cur = now["mods"].get(m)
            if cur and t.get("load") == "loaded" and cur["load"] != "loaded" and has_op(m, "load"):
                svc = self.hub.services.get(m)
                b = mem.needs(svc) if mem else 0
                steps.append({"action": "load", "target": m, "detail": f"load {m}", "bytes": b})
                needed += b
        avail = (mem.sys.get("available_bytes", 0) if mem and mem.sys else 0)
        reserve = round(self.hub.config.memory.reserve_gb * GB)
        after = avail + freed - needed - reserve
        return {"session": sid, "steps": steps, "memory": {"available_bytes": avail, "freed_bytes": freed, "needed_bytes": needed,
                                                           "reserve_bytes": reserve, "after_bytes": after, "fits": after >= 0}}

    async def restore(self, sid: str, dry_run: bool = False) -> dict[str, Any]:
        plan = await self.plan(sid)
        if dry_run:
            return {**plan, "dry_run": True}
        if self.restoring:
            raise SessionError(409, "busy", f"already restoring {self.restoring}")
        self.restoring = sid
        mgr = self.hub.services
        results = []
        try:
            for st in plan["steps"]:
                res: dict[str, Any] = {**{k: v for k, v in st.items() if k != "spec"}, "ok": True}
                try:
                    if st["action"] == "stop_llm":
                        lc = mgr.get("lcpp")
                        r = await self.client.delete(f"{lc.url}/api/instances/{st['target']}")
                        res["ok"] = r.status_code < 400
                    elif st["action"] == "unload":
                        await loading.unload(mgr, st["target"])
                        await self._until(lambda t=st["target"]: mgr.get(t).load in ("unloaded", "n/a"), 120)
                    elif st["action"] == "start":
                        svc = await mgr.start(st["target"], wait=True)
                        res["ok"] = svc.up
                    elif st["action"] == "launch_llm":
                        lc = mgr.get("lcpp")
                        if not lc.up:
                            await mgr.start("lcpp", wait=True)
                        r = await self.client.post(f"{lc.url}/api/instances", json=st["spec"], headers={"X-AIHub-Make-Room": "1"})
                        res["ok"] = r.status_code < 400
                        if not res["ok"]:
                            res["error"] = r.text[:300]
                    elif st["action"] == "load":
                        await loading.load(mgr, st["target"], make_room=True)
                        await self._until(lambda t=st["target"]: mgr.get(t).load in ("loaded", "unloaded"), 900)
                        res["ok"] = mgr.get(st["target"]).load == "loaded"
                except Exception as e:  # noqa: BLE001
                    res.update(ok=False, error=f"{getattr(e, 'detail', None) or e}"[:300])
                results.append(res)
                self.hub.bus.publish({"type": "session_step", "session": sid, "step": res})
        finally:
            self.restoring = None
        name = (await self.get(sid))["name"]
        ok = all(r["ok"] for r in results)
        if self.hub.activity:
            await self.hub.activity.add(f"Session {name} restored" + ("" if ok else " (with problems)"), level="info" if ok else "warn")
        return {**plan, "dry_run": False, "results": results, "ok": ok}

    @staticmethod
    async def _until(cond: Any, timeout: float) -> None:
        end = time.monotonic() + timeout
        while time.monotonic() < end and not cond():
            await asyncio.sleep(0.5)
