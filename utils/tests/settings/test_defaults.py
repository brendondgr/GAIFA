"""settings-redesign 4.1: `GET /api/settings/defaults`, the `Settings` shape from config.example.toml, unchanged by config.toml."""

from __future__ import annotations

import httpx

from utils.api_models import Settings
from utils.config import EXAMPLE
from utils.tests.settings.test_settings import _hub

EXAMPLE_TOML = """[hub]
port = 7000
[memory]
reserve_gb = 9
never_unload = ["lcpp"]
priority = ["comfy", "tts"]
[ui]
density = "comfortable"
[services]
order = ["relay", "lcpp"]
[agent.judge]
threshold = 0.4
"""


async def test_defaults_come_from_the_example(rig, serve):
    (rig.root / EXAMPLE).write_text(EXAMPLE_TOML)
    served = await _hub(rig, serve, "[memory]\nreserve_gb = 20\n[ui]\ntheme = \"dark\"\n")
    async with httpx.AsyncClient(base_url=served.url) as c:
        r = await c.get("/api/settings/defaults")
        assert r.status_code == 200, r.text
        d = r.json()
        Settings.model_validate(d)
        assert d["hub"]["port"] == 7000 and d["memory"]["reserve_gb"] == 9 and d["judge"]["threshold"] == 0.4
        assert d["ui"]["theme"] == "system" and d["ui"]["density"] == "comfortable"       # not this machine's dark
        assert d["memory"]["priority"] == ["comfy", "tts", "fake-ok"]                      # the installed mods follow, as in GET /api/settings
        assert d["services"]["order"] == ["relay", "lcpp", "fake-ok"]
        assert d["services"]["enabled"] == {"fake-ok": True} and d["services"]["autostart"] == {"fake-ok": True}
        assert (await c.get("/api/settings")).json()["memory"]["reserve_gb"] == 20
        # a changed config.toml doesn't change the answer
        await c.put("/api/settings", json={"memory": {"reserve_gb": 30}, "judge": {"threshold": 0.9}})
        assert (await c.get("/api/settings/defaults")).json() == d


async def test_without_the_example_the_built_in_defaults(rig, serve):
    served = await _hub(rig, serve)
    async with httpx.AsyncClient(base_url=served.url) as c:
        d = (await c.get("/api/settings/defaults")).json()
        Settings.model_validate(d)
        assert d["hub"]["port"] == 7000 and d["judge"]["model"] == "d3-lite" and d["judge"]["backend"] == "decide"
