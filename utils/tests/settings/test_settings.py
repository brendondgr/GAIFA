"""6.3: GET/PUT /api/settings: the shape, only real overrides written, comments kept, live
effects (memory reserve, disabling a mod), the port needing a restart, and refusals."""

from __future__ import annotations

import tomllib

import httpx

from utils.tests.services.conftest import ready, until


async def _hub(rig, serve, config: str = ""):
    rig.add("fake-ok")
    rig.config(config)
    served = await serve()
    await ready(served, "fake-ok")
    return served


def _file(served) -> str:
    p = served.hub.paths.config_file
    return p.read_text() if p.exists() else ""


async def test_get_and_save_whole_form_writes_nothing(rig, serve):
    served = await _hub(rig, serve, "# my settings\n[memory]\nreserve_gb = 12   # keep this comment\n")
    async with httpx.AsyncClient(base_url=served.url) as c:
        s = (await c.get("/api/settings")).json()
        assert s == {
            "hub": {"port": served.hub.config.hub.port},
            "memory": {"reserve_gb": 12, "auto_make_room": False, "never_unload": ["lcpp"], "priority": ["comfy", "tts", "gen3d"]},
            "services": {"order": ["relay", "lcpp", "tts", "gen3d", "comfy", "opencode"], "enabled": {"fake-ok": True}, "autostart": {"fake-ok": True}},
            "ui": {"theme": "system", "density": "compact", "dashboard": {"order": [], "hidden": [], "ranges": {}}},
        }
        before = _file(served)
        s["hub"]["port"] = served.hub.config.hub.port
        r = await c.put("/api/settings", json=s)
        assert r.status_code == 200 and r.json() == {"settings": s, "restart_required": False}
        assert _file(served) == before  # nothing changed, so nothing is rewritten (the comment stays)
        # a changed value equal to the default removes its key instead of pinning it
        await c.put("/api/settings", json={"memory": {"reserve_gb": 14}})
        assert tomllib.loads(_file(served))["memory"]["reserve_gb"] == 14
        await c.put("/api/settings", json={"memory": {"reserve_gb": 12}})
        assert "memory" not in tomllib.loads(_file(served)) and "# my settings" in _file(served)


async def test_memory_and_ui_changes_apply_at_once(rig, serve):
    served = await _hub(rig, serve, "[memory]\n# reserve for the desktop\nreserve_gb = 12\n")
    hub = served.hub
    async with httpx.AsyncClient(base_url=served.url) as c:
        r = await c.put("/api/settings", json={"memory": {"reserve_gb": 20, "never_unload": ["lcpp", "fake-ok"]},
                                               "ui": {"theme": "dark", "dashboard": {"order": ["kpi", "memory-time"], "hidden": ["heatmap"], "ranges": {"memory-time": "6h"}}}})
        assert r.status_code == 200 and not r.json()["restart_required"]
        s = r.json()["settings"]
        assert s["memory"]["reserve_gb"] == 20 and s["memory"]["never_unload"] == ["lcpp", "fake-ok"] and s["ui"]["theme"] == "dark"
        text = _file(served)
        assert "# reserve for the desktop" in text
        cfg = tomllib.loads(text)
        assert cfg["memory"]["reserve_gb"] == 20 and cfg["ui"] == {"theme": "dark", "dashboard": {
            "order": ["kpi", "memory-time"], "hidden": ["heatmap"], "ranges": {"memory-time": "6h"}}}
        assert hub.config.memory.reserve_gb == 20
        assert (await c.get("/api/memory")).json()["reserve_bytes"] == 20 * 1000**3
        # a later save without ui leaves the dashboard alone; an empty one removes it
        await c.put("/api/settings", json={"memory": {"auto_make_room": True}})
        assert tomllib.loads(_file(served))["ui"]["dashboard"]["hidden"] == ["heatmap"]
        await c.put("/api/settings", json={"ui": {"theme": "system", "dashboard": {"order": [], "hidden": [], "ranges": {}}}})
        assert "ui" not in tomllib.loads(_file(served))
        assert any(a["text"] == "AIHub settings saved" for a in hub.activity.recent(5))


async def test_disable_stops_the_mod_and_default_removes_the_key(rig, serve):
    served = await _hub(rig, serve)
    async with httpx.AsyncClient(base_url=served.url) as c:
        r = await c.put("/api/settings", json={"services": {"enabled": {"fake-ok": False}, "order": ["fake-ok"]}})
        assert r.status_code == 200 and r.json()["settings"]["services"]["enabled"] == {"fake-ok": False}
        await until(lambda: served.services.get("fake-ok").state == "stopped")
        cfg = tomllib.loads(_file(served))
        assert cfg["services"]["fake-ok"] == {"enabled": False} and cfg["services"]["order"] == ["fake-ok"]
        await c.put("/api/settings", json={"services": {"enabled": {"fake-ok": True}}})
        assert "fake-ok" not in tomllib.loads(_file(served)).get("services", {})
        assert served.services.get("fake-ok").state == "stopped"  # enabling doesn't start it


async def test_port_change_needs_a_restart_and_refusals(rig, serve):
    served = await _hub(rig, serve)
    async with httpx.AsyncClient(base_url=served.url) as c:
        r = await c.put("/api/settings", json={"hub": {"port": 7123}})
        assert r.status_code == 200 and r.json()["restart_required"] is True
        assert tomllib.loads(_file(served))["hub"]["port"] == 7123
        assert served.hub.port != 7123  # still listening where it started
        r = await c.put("/api/settings", json={"hub": {"port": served.hub.port}})
        assert r.json()["restart_required"] is False  # back to the port in use
        before = _file(served)
        for body, field in (({"hub": {"port": served.services.get("fake-ok").port}}, "hub.port"),
                            ({"hub": {"port": 80}}, "hub.port"),
                            ({"memory": {"reserve_gb": -1}}, "memory.reserve_gb"),
                            ({"memory": {"reserve_gb": 10**6}}, "memory.reserve_gb"),
                            ({"services": {"enabled": {"nope": True}}}, "services.enabled"),
                            ({"ui": {"density": "tiny"}}, "ui.density")):
            r = await c.put("/api/settings", json=body)
            assert r.status_code == 422 and r.json()["code"] == "invalid_config", body
            assert r.json()["data"]["field"] == field, body
        assert _file(served) == before  # nothing written
        r = await c.put("/api/settings", json={"extra": 1})
        assert r.status_code == 422 and r.json()["code"] == "invalid_request"


async def test_saved_port_does_not_change_the_running_port(make_app, root):
    app = make_app()  # no --port: the hub listens on config's hub.port
    hub = app.state.hub
    start = hub.port
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://hub") as c:
            r = await c.put("/api/settings", json={"hub": {"port": 7123}})
            assert r.json()["restart_required"] is True
            assert hub.port == start and (await c.get("/api/system")).json()["hub"]["port"] == start
