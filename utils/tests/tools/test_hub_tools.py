"""capability-enablement 1.7: hub_list_services says what each mod gives, its tools and its availability;
hub_enable_service turns a turned-off mod on and starts it; hub_start_service on a mod never set up answers not_set_up."""

from __future__ import annotations

import re
import shutil

import httpx
import pytest

from utils import config
from utils.tests.conftest import FAKE_MODS, free_port


def _copy(root, sid, edits=None):
    for helper in FAKE_MODS.glob("_*.py"):
        shutil.copy(helper, root / "services" / helper.name)
    d = root / "services" / sid
    shutil.copytree(FAKE_MODS / "fake-tools", d)
    text = (d / "service.toml").read_text().replace('id = "fake-tools"', f'id = "{sid}"').replace('name = "Fake Tools"', f'name = "{sid.title()}"')
    text = re.sub(r"(?m)^port = \d+", f"port = {free_port()}", text)
    for k, v in (edits or {}).items():
        text = text.replace("[run]\n", f"[run]\n{k} = {v}\n", 1) if not re.search(rf"(?m)^{k} = ", text) else re.sub(rf"(?m)^{k} = .*$", f"{k} = {v}", text)
    text = text.replace("[agent]\n", '[agent]\nprovides = "make fake things"\n', 1)
    (d / "service.toml").write_text(text)


@pytest.fixture
async def hub(root, make_app):
    _copy(root, "offmod")
    _copy(root, "fresh", {"command": '[".venv/bin/python", "server.py"]'})
    (root / "config.toml").write_text("[services.offmod]\nenabled = false\n")
    app = make_app(config.load(root / "config.toml"), port=7000, autostart=False)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://hub", timeout=60) as c:
            yield app, c


async def call(c, name, args):
    r = await c.post(f"/api/tools/{name}/call?wait=30", json={"arguments": args, "mode": "bypass", "origin": {}})
    assert r.status_code == 200, r.text
    return r.json()


async def test_list_services_says_what_works(hub):
    app, c = hub
    rows = {s["id"]: s for s in (await call(c, "hub_list_services", {}))["result"]["services"]}
    off = rows["offmod"]
    assert off["provides"] == "make fake things" and "offmod_get_item" in off["tools"]
    assert off["availability"] == {"status": "off", "why": "Offmod is turned off",
                                   "fix": {"command": "turn Offmod on in Settings → Services", "tool": "hub_enable_service"}}
    assert rows["fresh"]["availability"]["status"] == "not_set_up" and rows["fresh"]["availability"]["fix"]["command"] == "gaifa setup fresh"


async def test_enable_turns_it_on_and_starts_it(hub, root):
    app, c = hub
    tools = {t["name"]: t for t in (await c.get("/api/tools")).json()}
    assert tools["offmod_get_item"]["turn_on"] == {"tool": "hub_enable_service", "arguments": {"id": "offmod"},
                                                    "command": "turn Offmod on in Settings → Services"}
    out = await call(c, "hub_enable_service", {"id": "offmod"})
    assert out["status"] == "done" and out["result"]["enabled"] is True and out["result"]["state"] == "ready", out
    assert "enabled = false" not in (root / "config.toml").read_text()      # back to the default: the key is removed
    assert app.state.hub.services.get("offmod").eff.enabled is True
    got = await call(c, "offmod_get_item", {"item_id": "x"})
    assert got["status"] == "done"


async def test_start_on_a_mod_never_set_up(hub):
    app, c = hub
    out = await call(c, "hub_start_service", {"id": "fresh"})
    e = out["error"]
    assert out["status"] == "error" and e["code"] == "not_set_up" and "gaifa setup fresh" in e["fix"] and "don't retry" in e["fix"]
