"""capability-enablement 1.6: a mod's status may say some of its tools are off (`tools_off`): validated like tools_rev,
and the catalog marks those tools `off_by_mod`; a call answers capability_unavailable with the mod's own words."""

from __future__ import annotations

import json
import re
import shutil

import httpx
import pytest

from utils import config
from utils.services.status import validate
from utils.tests.conftest import FAKE_MODS, free_port


def test_parsed_and_checked_against_the_mods_tools():
    st, problems = validate({"tools_off": {"search": {"why": "no SearXNG answers", "fix": "set it up"}}}, {"search", "fetch"})
    assert problems == [] and st["tools_off"] == {"search": {"why": "no SearXNG answers", "fix": "set it up"}}
    _, problems = validate({"tools_off": {"surf": {"why": "x"}}}, {"search", "fetch"})
    assert problems == ["tools_off: 'surf' isn't one of the mod's tools (fetch, search)"]
    _, problems = validate({"tools_off": {"search": {"why": ""}}}, {"search"})
    assert problems and "must be" in problems[0]
    _, problems = validate({"tools_off": {"search": {"why": "x" * 201}}}, {"search"})
    assert problems
    _, problems = validate({"tools_off": ["search"]}, None)
    assert problems and "must be an object" in problems[0]
    st, problems = validate({"tools_off": {"anything": {"why": "x"}}}, None)   # a tools_source mod: names can't be known here
    assert problems == [] and st["tools_off"] == {"anything": {"why": "x", "fix": ""}}
    st, _ = validate({})
    assert st["tools_off"] == {}


@pytest.fixture
async def hub(root, make_app):
    for helper in FAKE_MODS.glob("_*.py"):
        shutil.copy(helper, root / "services" / helper.name)
    d = root / "services" / "fake-tools"
    shutil.copytree(FAKE_MODS / "fake-tools", d)
    text = re.sub(r"(?m)^port = \d+", f"port = {free_port()}", (d / "service.toml").read_text())
    off = json.dumps({"get_item": {"why": "the item store is offline", "fix": "tell the user the store is down"}})
    text = text.replace('env = { FAKE_PORT = "{port}", FAKE_OUTPUTS = "{outputs}" }',
                        'env = { FAKE_PORT = "{port}", FAKE_OUTPUTS = "{outputs}", FAKE_TOOLS_OFF = ' + json.dumps(off) + ' }')
    (d / "service.toml").write_text(text)
    app = make_app(config.load(root / "config.toml"), port=7000, autostart=True)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://hub", timeout=60) as c:
            from utils.tests.tools.conftest import wait_ready
            await wait_ready(c, "fake-tools")
            from utils.tests.services.conftest import until
            await until(lambda: app.state.hub.services.get("fake-tools").tools_off)
            yield app, c


async def test_the_catalog_and_a_call_follow_it(hub):
    app, c = hub
    tools = {t["name"]: t for t in (await c.get("/api/tools")).json()}
    t = tools["fake_tools_get_item"]
    assert (t["state"], t["available"], t["why"]) == ("off_by_mod", False, "the item store is offline")
    assert tools["fake_tools_make_image"]["state"] == "on" and tools["fake_tools_make_image"]["available"] is True
    r = await c.post("/api/tools/fake_tools_get_item/call?wait=10", json={"arguments": {"item_id": "a"}, "mode": "bypass", "origin": {}})
    e = r.json()["error"]
    assert e["code"] == "capability_unavailable" and e["state"] == "off_by_mod"
    assert e["detail"].endswith(": the item store is offline")
    assert e["fix"].startswith("tell the user the store is down") and "don't retry" in e["fix"]
    app.state.hub.services.get("fake-tools").tools_off = {}          # the mod says it's back
    tools = {t["name"]: t for t in (await c.get("/api/tools")).json()}
    assert tools["fake_tools_get_item"]["state"] == "on" and tools["fake_tools_get_item"]["available"] is True
