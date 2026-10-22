"""2.7: the service routes (brief §6.2) against a real server with fake mods."""

from __future__ import annotations

import asyncio
import json
import time
import tomllib

import httpx
import pytest

from utils.api_models import ServiceDetail, ServiceSummary
from utils.tests.conftest import free_port
from utils.tests.services.conftest import ready, until


@pytest.fixture
async def hub(rig, serve):
    rig.add("fake-ok")
    rig.add("fake-mem")
    rig.config("# my comment survives\n[services]\norder = [\"fake-mem\"]\n\n[services.fake-ok]\nenv = { KEEP = \"1\", DROP = \"2\" }  # env comment")
    served = await serve()
    await ready(served, "fake-ok", "fake-mem")
    return served


async def test_list_in_sidebar_order_with_full_summaries(hub):
    async with httpx.AsyncClient(base_url=hub.url) as c:
        r = await c.get("/api/services")
    assert r.status_code == 200
    items = r.json()
    assert [s["id"] for s in items] == ["fake-mem", "fake-ok"]  # config order first
    for s in items:
        ServiceSummary.model_validate(s)
        assert s["state"] == "ready"
    mem = items[0]
    # The manifest's estimate until the first status poll, then the mod's own (rounded) figure.
    assert mem["load"] == "unloaded" and mem["memory"]["estimate_bytes"] in (round(0.0625 * 1000**3), round(0.062 * 1000**3))


async def test_detail(hub, rig):
    async with httpx.AsyncClient(base_url=hub.url) as c:
        r = await c.get("/api/services/fake-ok")
    d = r.json()
    ServiceDetail.model_validate(d)
    assert d["folder"] == "services/fake-ok" and d["outputs_dir"] == "outputs/fake-ok"
    assert d["pid"] and d["command"][0] == "python3" and d["command"][1].endswith("services/_fakemod.py")
    assert d["health"]["ok"] and d["manifest"]["id"] == "fake-ok"
    assert d["config"] == {"enabled": True, "autostart": True, "port": rig.ports["fake-ok"], "idle_unload_s": None, "auto_unload": True, "priority": 100, "env": {"KEEP": "1", "DROP": "2"}, "accel": None}


async def test_start_stop_restart(hub):
    async with httpx.AsyncClient(base_url=hub.url, timeout=30) as c:
        r = await c.post("/api/services/fake-ok/stop")
        assert r.status_code == 202 and r.json()["state"] == "stopping"
        await until(lambda: hub.services.get("fake-ok").state == "stopped")
        r = await c.post("/api/services/fake-ok/start")
        assert r.status_code == 202 and r.json()["state"] == "starting"
        r = await c.post("/api/services/fake-ok/restart?wait=1")
        assert r.status_code == 202 and r.json()["state"] == "ready"
        r = await c.post("/api/services/fake-ok/stop?wait=true")
        assert r.json()["state"] == "stopped"


async def test_errors_use_the_envelope(hub, rig):
    async with httpx.AsyncClient(base_url=hub.url) as c:
        r = await c.get("/api/services/nope")
        assert (r.status_code, r.json()["code"], r.headers["x-aihub-error"]) == (404, "service_not_found", "service_not_found")
        r = await c.post("/api/services/fake-ok/load")
        assert (r.status_code, r.json()["code"]) == (409, "not_unloadable")
        r = await c.get("/api/services/fake-ok/logs?lines=0")
        assert (r.status_code, r.json()["code"]) == (422, "invalid_request")
        await c.post("/api/services/fake-mem/stop?wait=1")
        r = await c.post("/api/services/fake-mem/load")
        assert (r.status_code, r.json()["code"]) == (503, "service_not_running")


async def test_load_and_unload(hub, rig):
    svc = hub.services.get("fake-mem")
    async with httpx.AsyncClient(base_url=hub.url) as c:
        r = await c.post("/api/services/fake-mem/load")
        assert r.status_code == 202 and r.json()["load"] == "loading"
        await until(lambda: svc.load == "loaded")
        status = (await c.get(f"{svc.url}/v1/status")).json()
        assert status["loaded"] is True
        r = await c.post("/api/services/fake-mem/load")  # already loaded: nothing to do
        assert r.json()["load"] == "loaded"
        r = await c.post("/api/services/fake-mem/unload")
        assert r.json()["load"] == "unloading"
        await until(lambda: svc.load == "unloaded")
    texts = [a["text"] for a in hub.hub.activity.recent(50)]
    assert any(t.startswith("Loaded Fake Memory (") for t in texts) and any(t.startswith("Unloaded Fake Memory (") for t in texts)


async def test_failed_load_goes_back_and_says_why(rig, serve):
    d = rig.add("fake-ok", as_id="badload")
    (d / "service.toml").write_text((d / "service.toml").read_text() + '\n[memory]\nload = "POST /v1/nope"\nunload = "POST /v1/nope"\n')
    served = await serve()
    await ready(served, "badload")
    svc = served.services.get("badload")
    async with httpx.AsyncClient(base_url=served.url) as c:
        await c.post("/api/services/badload/load")
    await until(lambda: svc.load == "unloaded" and any("load failed" in a["text"] for a in served.hub.activity.recent(10)))
    item = next(a for a in served.hub.activity.recent(10) if "load failed" in a["text"])
    assert item["text"] == "Bad Load: load failed (HTTP 404: no route /v1/nope)" or item["text"].endswith("load failed (HTTP 404: no route /v1/nope)")
    assert item["level"] == "error"


async def test_logs_and_log_stream(rig, serve):
    rig.add("fake-ok")
    rig.config('[services.fake-ok]\nenv = { FAKE_VERBOSE = "1" }')
    served = await serve()
    await ready(served, "fake-ok")
    async with httpx.AsyncClient(base_url=served.url, timeout=10) as c:
        r = await c.get("/api/services/fake-ok/logs?lines=5")
        lines = r.json()["lines"]
        assert 0 < len(lines) <= 5 and set(lines[0]) == {"ts", "text", "stream"}
        got: list[dict] = []

        async def read():
            async with c.stream("GET", "/api/services/fake-ok/logs/stream") as s:
                assert s.headers["content-type"].startswith("text/event-stream")
                async for line in s.aiter_lines():
                    if line.startswith("data:"):
                        got.append(json.loads(line[5:]))
                        if any("/v1/echo" in g["text"] for g in got):
                            return

        task = asyncio.create_task(read())
        await asyncio.sleep(0.3)
        await c.post("/api/s/fake-ok/v1/echo", json={})
        await asyncio.wait_for(task, 5)
    assert any("POST /v1/echo" in g["text"] for g in got)


async def test_log_stream_ends_on_shutdown(rig, serve):
    rig.add("fake-ok")
    served = await serve()
    await ready(served, "fake-ok")
    t0 = None

    async def read():
        async with httpx.AsyncClient(base_url=served.url, timeout=30) as c:
            async with c.stream("GET", "/api/services/fake-ok/logs/stream") as s:
                async for _ in s.aiter_lines():
                    pass

    task = asyncio.create_task(read())
    await asyncio.sleep(0.3)
    t0 = time.monotonic()
    served.hub.bus.close()  # what app.py does on SIGTERM
    await asyncio.wait_for(task, 5)
    assert time.monotonic() - t0 < 2


async def test_events_stream_carries_service_events(hub):
    got: list[dict] = []
    async with httpx.AsyncClient(base_url=hub.url, timeout=10) as c:

        async def read():
            async with c.stream("GET", "/api/events") as s:
                async for line in s.aiter_lines():
                    if line.startswith("data:"):
                        ev = json.loads(line[5:])
                        got.append(ev)
                        mine = [e["service"]["state"] for e in got if e["type"] == "service" and e["service"]["id"] == "fake-ok"]
                        # Status polls also publish `service` events; wait for ready *after* the stop.
                        if "stopped" in mine and mine[-1] == "ready":
                            return

        task = asyncio.create_task(read())
        await asyncio.sleep(0.2)
        await c.post("/api/services/fake-ok/restart")
        await asyncio.wait_for(task, 10)
    states = [e["service"]["state"] for e in got if e["type"] == "service" and e["service"]["id"] == "fake-ok"]
    changes = [st for i, st in enumerate(states) if i == 0 or st != states[i - 1]]
    assert changes[-4:] == ["stopping", "stopped", "starting", "ready"], states
    assert any(e["type"] == "activity" for e in got)


async def test_config_js_lists_the_live_areas(hub):
    async with httpx.AsyncClient(base_url=hub.url) as c:
        text = (await c.get("/config.js")).text
    areas = json.loads(text.split("AIHUB_LIVE_AREAS = ")[1].rstrip(";\n"))
    assert set(areas) == {"system", "services", "logs", "operations", "proxy", "events", "models", "outputs", "memory", "metrics", "widgets", "overview", "settings", "tools", "sessions", "prefs", "webpages", "gpu"}


# --- PUT config ---------------------------------------------------------------------------------


async def test_save_config_restart_required_and_comments_kept(hub, rig):
    cfg_file = rig.root / "config.toml"
    async with httpx.AsyncClient(base_url=hub.url) as c:
        r = await c.put("/api/services/fake-ok/config", json={"port": 5999, "env": {"KEEP": "1", "NEW": "3"}, "idle_unload_s": 120, "priority": 5})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["restart_required"] is True
    assert body["config"]["port"] == 5999 and body["config"]["env"] == {"KEEP": "1", "NEW": "3"} and body["config"]["priority"] == 5
    text = cfg_file.read_text()
    assert "# my comment survives" in text
    saved = tomllib.loads(text)["services"]["fake-ok"]
    assert saved["env"] == {"KEEP": "1", "NEW": "3"} and saved["port"] == 5999 and saved["idle_unload_s"] == 120  # DROP is gone
    svc = hub.services.get("fake-ok")
    assert svc.eff.port == 5999 and svc.port == rig.ports["fake-ok"] and svc.state == "ready"  # the new port applies at the next start
    async with httpx.AsyncClient(base_url=hub.url) as c:
        r = await c.put("/api/services/fake-ok/config", json={"idle_unload_s": None})
    assert r.json()["config"]["idle_unload_s"] is None and r.json()["restart_required"] is False
    assert "idle_unload_s" not in tomllib.loads(cfg_file.read_text())["services"]["fake-ok"]


async def test_disabling_stops_now_and_autostart_applies(hub):
    async with httpx.AsyncClient(base_url=hub.url) as c:
        r = await c.put("/api/services/fake-ok/config", json={"enabled": False})
        assert r.json() == {"config": {**r.json()["config"], "enabled": False}, "restart_required": False}
        await until(lambda: hub.services.get("fake-ok").state == "stopped")
        r = await c.post("/api/services/fake-ok/start")
        assert (r.status_code, r.json()["code"]) == (409, "service_disabled")
        r = await c.put("/api/services/fake-ok/config", json={"enabled": True, "autostart": False})
        assert r.json()["config"]["autostart"] is False
        r = await c.get("/api/services/fake-ok")
        assert r.json()["enabled"] is True and r.json()["autostart"] is False


async def test_invalid_config_changes_nothing(hub, rig):
    cfg_file = rig.root / "config.toml"
    before = cfg_file.read_text()
    async with httpx.AsyncClient(base_url=hub.url) as c:
        r = await c.put("/api/services/fake-ok/config", json={"port": rig.ports["fake-mem"]})
        assert (r.status_code, r.json()["code"]) == (422, "invalid_config")
        assert f"port {rig.ports['fake-mem']} is already used by fake-mem" in r.json()["detail"]
        r = await c.put("/api/services/fake-ok/config", json={"port": hub.port})
        assert (r.status_code, r.json()["code"]) == (422, "invalid_config")
        r = await c.put("/api/services/fake-ok/config", json={"port": 70000})
        assert (r.status_code, r.json()["code"]) == (422, "invalid_request")
        r = await c.put("/api/services/fake-ok/config", json={"prot": 1})
        assert (r.status_code, r.json()["code"]) == (422, "invalid_request")
    assert cfg_file.read_text() == before


async def test_openapi_documents_the_routes(hub):
    async with httpx.AsyncClient(base_url=hub.url) as c:
        doc = (await c.get("/api/openapi.json")).json()
    for path in ("/api/services", "/api/services/{service_id}", "/api/services/{service_id}/start", "/api/services/{service_id}/config",
                 "/api/services/{service_id}/logs/stream", "/api/services/{service_id}/operations"):
        assert path in doc["paths"], path
    assert "ServiceSummary" in doc["components"]["schemas"]
    assert not any(p.startswith("/api/s/") for p in doc["paths"])  # the proxy isn't part of the hub's own API


async def test_recent_events(hub):
    svc = hub.services.get("fake-ok")
    async with httpx.AsyncClient(base_url=hub.url) as c:
        await c.post(f"{svc.url}/v1/jobs", json={"label": "long", "seconds": 30})
        await until(lambda: svc.jobs)
        r = (await c.get("/api/events/recent?limit=5")).json()
    assert len(r["activity"]) <= 5 and any("is ready" in a["text"] for a in r["activity"])
    assert r["alerts"] == [] and r["jobs"][0]["service"] == "fake-ok" and r["jobs"][0]["state"] == "running"


async def test_saving_defaults_writes_nothing(hub, rig):
    cfg_file = rig.root / "config.toml"
    async with httpx.AsyncClient(base_url=hub.url) as c:
        cur = (await c.get("/api/services/fake-mem")).json()["config"]
        r = await c.put("/api/services/fake-mem/config", json=cur)  # the whole form, unchanged
        assert r.status_code == 200 and r.json()["restart_required"] is False
        assert "fake-mem" not in tomllib.loads(cfg_file.read_text()).get("services", {})
        r = await c.put("/api/services/fake-mem/config", json={**cur, "autostart": False})
        assert tomllib.loads(cfg_file.read_text())["services"]["fake-mem"] == {"autostart": False}
        r = await c.put("/api/services/fake-mem/config", json={**cur, "autostart": True})  # back to the default
        assert tomllib.loads(cfg_file.read_text())["services"].get("fake-mem", {}) == {}
        # fake-ok has env in config.toml; sending the manifest default ({}) removes it
        r = await c.put("/api/services/fake-ok/config", json={"env": {}})
        assert "fake-ok" not in tomllib.loads(cfg_file.read_text())["services"]  # env was its only key
        assert r.json()["config"]["env"] == {}


async def test_port_change_applies_at_the_next_start(hub, rig):
    """Changing the port of a running mod must not break it (health and proxy stay on the old port)."""
    svc = hub.services.get("fake-ok")
    old_port = svc.port
    new_port = free_port()
    async with httpx.AsyncClient(base_url=hub.url) as c:
        r = await c.put("/api/services/fake-ok/config", json={"port": new_port})
        assert r.json()["restart_required"] is True and r.json()["config"]["port"] == new_port
        await asyncio.sleep(1.0)  # ~10 health checks at the test timing
        assert svc.state == "ready" and svc.port == old_port
        assert (await c.get("/api/s/fake-ok/health")).status_code == 200
        assert (await c.get("/api/services/fake-ok")).json()["port"] == old_port
        r = await c.post("/api/services/fake-ok/restart?wait=1")
    assert r.json()["state"] == "ready" and r.json()["port"] == new_port and svc.port == new_port
