"""capability-enablement 1.5: tools that say they're off. Every mod's tools stay in the catalog whatever its state, with
`state` and `turn_on`; a call to one whose mod is not set up, off or broken answers `capability_unavailable` at once with
no start tried; a set-up mod that never ran is started by its first call, which then runs; after a failed start, calls
fail at once for a minute."""

from __future__ import annotations

import re
import shutil
import time

import httpx
import pytest

from utils import config
from utils.tests.conftest import FAKE_MODS, free_port

MODS = {   # id → (manifest edits, config lines)
    "fresh": ({"command": '[".venv/bin/python", "server.py"]'}, ""),
    "offmod": ({}, "[services.offmod]\nenabled = false\n"),
    "idle": ({}, "[services.idle]\nautostart = false\n"),
    "dud": ({"command": '["python3", "-c", "raise SystemExit(1)"]', "installed": '"sh"'}, "[services.dud]\nautostart = false\n"),
}


def _copy(root, sid: str, edits: dict[str, str]) -> None:
    for helper in FAKE_MODS.glob("_*.py"):
        shutil.copy(helper, root / "services" / helper.name)
    d = root / "services" / sid
    shutil.copytree(FAKE_MODS / "fake-tools", d)
    text = (d / "service.toml").read_text().replace('id = "fake-tools"', f'id = "{sid}"')
    text = text.replace('name = "Fake Tools"', f'name = "{sid.title()}"')
    text = re.sub(r"(?m)^port = \d+", f"port = {free_port()}", text)
    for k, v in edits.items():
        text = re.sub(rf"(?m)^{k} = .*$", f"{k} = {v}", text) if re.search(rf"(?m)^{k} = ", text) else text.replace("[run]\n", f"[run]\n{k} = {v}\n", 1)
    text = text.replace("[agent]\n", '[agent]\nprovides = "make fake things"\n', 1)
    (d / "service.toml").write_text(text)


@pytest.fixture
async def hub(root, make_app):
    for sid, (edits, _) in MODS.items():
        _copy(root, sid, edits)
    (root / "config.toml").write_text("".join(c for _, c in MODS.values()))
    app = make_app(config.load(root / "config.toml"), port=7000, autostart=True)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://hub", timeout=60) as c:
            yield app, c


async def call(c, name, args=None):
    r = await c.post(f"/api/tools/{name}/call?wait=30", json={"arguments": args or {}, "mode": "bypass", "origin": {}})
    assert r.status_code == 200, r.text
    return r.json()


async def test_every_tool_listed_with_its_state(hub):
    app, c = hub
    tools = {t["name"]: t for t in (await c.get("/api/tools")).json()}
    assert tools["fresh_get_item"]["state"] == "not_set_up" and tools["fresh_get_item"]["why"] == "Fresh isn't set up on this machine"
    assert tools["fresh_get_item"]["turn_on"] == {"tool": "", "arguments": {}, "command": "gaifa setup fresh"}
    assert tools["offmod_get_item"]["state"] == "off" and tools["offmod_get_item"]["why"] == "Offmod is turned off"
    idle = tools["idle_get_item"]
    assert idle["state"] == "starts_on_use" and idle["turn_on"]["tool"] == "hub_start_service" and idle["turn_on"]["arguments"] == {"id": "idle"}
    assert all(t["state"] == "on" for t in tools.values() if t["mod"] == "hub")
    model = {t["name"]: t for t in (await c.get("/api/tools", params={"view": "model"})).json()}
    assert model["fresh_get_item"]["state"] == "not_set_up"


async def test_not_set_up_answers_at_once_with_what_is_missing(hub):
    app, c = hub
    t0 = time.monotonic()
    out = await call(c, "fresh_get_item", {"item_id": "a"})
    assert time.monotonic() - t0 < 1
    e = out["error"]
    assert out["status"] == "error" and e["code"] == "capability_unavailable" and e["state"] == "not_set_up"
    assert e["detail"] == "I can't make fake things: Fresh isn't set up on this machine"
    assert "offer to set it up (`gaifa setup fresh`" in e["fix"] and "don't retry" in e["fix"]
    assert e["fixes"] == [{"label": "Set up Fresh", "setup": "fresh", "command": "gaifa setup fresh"}]
    assert app.state.hub.services.get("fresh").state == "stopped"          # nothing launched


async def test_off_answers_with_turn_on(hub):
    app, c = hub
    e = (await call(c, "offmod_get_item", {"item_id": "a"}))["error"]
    assert e["code"] == "capability_unavailable" and e["state"] == "off"
    assert e["fixes"] == [{"label": "Turn on Offmod", "service": "offmod", "action": "enable"}]
    assert "ask the user to turn Offmod on" in e["fix"]
    assert app.state.hub.services.get("offmod").state == "stopped"


async def test_a_never_run_mod_is_started_by_its_first_call(hub):
    app, c = hub
    svc = app.state.hub.services.get("idle")
    assert svc.state == "stopped"
    out = await call(c, "idle_get_item", {"item_id": "a7"})
    assert out["status"] == "done", out
    assert svc.up
    tools = {t["name"]: t for t in (await c.get("/api/tools")).json()}
    assert tools["idle_get_item"]["state"] == "on" and tools["idle_get_item"]["available"] is True


async def test_after_a_failed_start_calls_fail_at_once(hub):
    app, c = hub
    first = await call(c, "dud_get_item", {"item_id": "a"})
    assert first["status"] == "error" and first["error"]["code"] == "service_not_running"
    svc = app.state.hub.services.get("dud")
    assert svc.start_failed_at
    launches = []
    real = app.state.hub.services.backend.start

    async def counting(spec):
        launches.append(spec)
        return await real(spec)

    app.state.hub.services.backend.start = counting
    t0 = time.monotonic()
    second = await call(c, "dud_get_item", {"item_id": "b"})
    assert time.monotonic() - t0 < 1 and launches == []
    e = second["error"]
    assert e["code"] in ("service_not_running", "capability_unavailable")
    assert "don't retry" in e["fix"] or "don't retry" in e.get("fix", "")


async def test_mcp_lists_the_state(hub):
    app, c = hub
    r = await c.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                     headers={"Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2025-06-18"})
    assert r.status_code == 200, r.text
    tools = {t["name"]: t for t in r.json()["result"]["tools"]}
    assert tools["fresh_get_item"]["_meta"]["gaifa/state"] == "not_set_up"
    assert "Not available: Fresh isn't set up" in tools["fresh_get_item"]["description"]
    assert tools["idle_get_item"]["_meta"]["gaifa/state"] in ("starts_on_use", "on")
