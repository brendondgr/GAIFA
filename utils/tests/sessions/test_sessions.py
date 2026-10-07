"""Phase 15: snapshots, routes, the restore plan and run (through the memory manager with two
fake-mem mods), auto-save at shutdown, the unclean-shutdown flag, restore at boot, and the tools."""

from __future__ import annotations

import asyncio
import re

import httpx

from utils import config
from utils.tests.conftest import free_port
from utils.tests.tools.conftest import wait_ready


def _mods(services_dir, *ids):
    services = services_dir(*ids)
    for i in ids:
        toml = services / i / "service.toml"
        toml.write_text(re.sub(r"(?m)^port = \d+", f"port = {free_port()}", toml.read_text()))
    return services


async def _app(make_app, cfg):
    return make_app(cfg, port=7000, autostart=True)


async def test_save_switch_and_restore(services_dir, root, make_app):
    _mods(services_dir, "fake-mem", "fake-ok")
    cfg = config.load(root / "config.toml")
    app = await _app(make_app, cfg)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://hub", timeout=60) as c:
            await wait_ready(c, "fake-mem")
            await wait_ready(c, "fake-ok")
            await c.post("/api/services/fake-mem/load")
            for _ in range(100):
                if (await c.get("/api/services/fake-mem")).json()["load"] == "loaded":
                    break
                await asyncio.sleep(0.1)
            a = (await c.post("/api/sessions", json={"name": "Work A"})).json()
            assert a["snapshot"]["mods"]["fake-mem"] == {"running": True, "load": "loaded"} and "loaded: fake-mem" in a["summary"]
            await c.post("/api/services/fake-mem/unload")
            await c.post("/api/services/fake-ok/stop?wait=1")
            b = (await c.post("/api/sessions", json={"name": "Work B"})).json()
            assert b["snapshot"]["mods"]["fake-mem"]["load"] != "loaded" and not b["snapshot"]["mods"]["fake-ok"]["running"]
            names = [s["name"] for s in (await c.get("/api/sessions")).json()]
            assert names[:2] == ["Work B", "Work A"]
            dry = (await c.post(f"/api/sessions/{a['id']}/restore?dry_run=1")).json()
            assert [s["action"] for s in dry["steps"]] == ["start", "load"] and dry["dry_run"] is True
            assert dry["memory"]["fits"] is True
            assert (await c.get("/api/services/fake-ok")).json()["state"] == "stopped"    # a dry run changes nothing
            r = (await c.post(f"/api/sessions/{a['id']}/restore")).json()
            assert r["ok"] is True and [x["ok"] for x in r["results"]] == [True, True]
            assert (await c.get("/api/services/fake-ok")).json()["state"] == "ready"
            assert (await c.get("/api/services/fake-mem")).json()["load"] == "loaded"
            back = (await c.post("/api/sessions/Work B/restore")).json()
            assert [s["action"] for s in back["steps"]] == ["unload"] and back["ok"]
            # rename, conflicts, delete
            assert (await c.put(f"/api/sessions/{a['id']}", json={"name": "LLM work"})).json()["name"] == "LLM work"
            assert (await c.put(f"/api/sessions/{a['id']}", json={"name": "Work B"})).status_code == 409
            assert (await c.delete(f"/api/sessions/{b['id']}")).status_code == 204
            assert (await c.get("/api/sessions/Work B")).status_code in (404, 405)
            assert (await c.post("/api/sessions/nope/restore")).json()["code"] == "not_found"
            # the tools
            t = (await c.post("/api/tools/hub_list_sessions/call", json={"arguments": {}})).json()
            assert [s["name"] for s in t["result"]["sessions"]] == ["LLM work"]
            t = (await c.post("/api/tools/hub_restore_session/call", json={"arguments": {"name": "LLM work"}})).json()
            assert t["status"] == "needs_approval"
            t = (await c.post("/api/tools/hub_restore_session/call?wait=30", json={"arguments": {"name": "LLM work", "dry_run": True}, "mode": "auto"})).json()
            assert t["status"] == "done" and t["result"]["fits"] is True


async def test_autosave_at_shutdown_unclean_flag_and_restore_on_boot(services_dir, root, make_app):
    _mods(services_dir, "fake-ok")
    cfg = config.load(root / "config.toml")
    app = await _app(make_app, cfg)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://hub") as c:
            await wait_ready(c, "fake-ok")
            st = (await c.get("/api/sessions/state")).json()
            assert st["unclean_shutdown"] is False and st["last_auto"] is None
    # a clean stop saved "Last session"
    app = await _app(make_app, cfg)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://hub") as c:
            st = (await c.get("/api/sessions/state")).json()
            assert st["unclean_shutdown"] is False and st["last_auto"]["name"] == "Before restart"
            assert st["last_auto"]["snapshot"]["mods"]["fake-ok"]["running"] is True
            # the auto-save after the start replaces "Last session" but never "Before restart" (the reboot bug)
            await c.post("/api/services/fake-ok/stop?wait=1")
            await app.state.hub.sessions.save("Last session", auto=True)
            st = (await c.get("/api/sessions/state")).json()
            assert st["last_auto"]["snapshot"]["mods"]["fake-ok"]["running"] is True
            await c.post("/api/services/fake-ok/start?wait=1")
            await app.state.hub.sessions.save("Last session", auto=True)    # the latest auto-save: fake-ok running
            await app.state.hub.db.execute("UPDATE kv SET value = '0' WHERE key = 'sessions:clean_shutdown'")
            app.state.hub.config.sessions.autosave_s = 0      # stop like a crash: nothing saved, the flag stays 0
            app.state.hub.sessions._kv = lambda *a: asyncio.sleep(0)
            await wait_ready(c, "fake-ok")
            await c.post("/api/services/fake-ok/stop?wait=1")
    cfg.sessions.restore_on_boot = True
    cfg.services.overrides["fake-ok"] = config.ServiceOverride(autostart=False)
    app = await _app(make_app, cfg)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://hub") as c:
            st = (await c.get("/api/sessions/state")).json()
            assert st["unclean_shutdown"] is True and st["restore_on_boot"] is True
            for _ in range(150):      # "Before restart" had fake-ok running: restore-at-boot starts it
                if (await c.get("/api/services/fake-ok")).json()["state"] == "ready":
                    break
                await asyncio.sleep(0.1)
            assert (await c.get("/api/services/fake-ok")).json()["state"] == "ready"


async def test_mods_without_load_ops_are_left_to_their_own_steps(services_dir, root, make_app):
    """lcpp reports `loaded` from its instances and has no load operation: a session switch must not
    try to load or unload it (its instances are stopped and launched as their own steps)."""
    _mods(services_dir, "fake-ok")
    cfg = config.load(root / "config.toml")
    app = await _app(make_app, cfg)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://hub", timeout=60) as c:
            await wait_ready(c, "fake-ok")
            s = app.state.hub.sessions
            snap = await s.snapshot()
            snap["mods"]["fake-ok"]["load"] = "loaded"          # as lcpp reports it
            saved = await s.save("Odd", snapshot=snap)
            plan = (await c.post(f"/api/sessions/{saved['id']}/restore?dry_run=1")).json()
            assert not [st for st in plan["steps"] if st["target"] == "fake-ok"]
