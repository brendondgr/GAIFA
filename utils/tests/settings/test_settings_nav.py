"""33.2: `[ui.nav]`, the sidebar's choices: defaults, a save written and read back, defaults removing the table, refusals."""

from __future__ import annotations

import tomllib

import httpx

from utils.tests.settings.test_settings import _file, _hub

DEFAULT = {"collapsed": False, "services": "list", "hidden": [], "folded": False}


async def test_nav_round_trip(rig, serve):
    served = await _hub(rig, serve, "# mine\n[ui]\ntheme = \"dark\"\n")
    async with httpx.AsyncClient(base_url=served.url) as c:
        assert (await c.get("/api/settings")).json()["ui"]["nav"] == DEFAULT
        nav = {"collapsed": True, "services": "counts", "hidden": ["fake-ok", "gone-mod"], "folded": False}
        r = await c.put("/api/settings", json={"ui": {"nav": nav}})
        assert r.status_code == 200 and r.json()["settings"]["ui"]["nav"] == nav
        cfg = tomllib.loads(_file(served))
        # only what differs from the defaults is written; the rest of [ui] and the comment stay
        assert cfg["ui"]["nav"] == {"collapsed": True, "services": "counts", "hidden": ["fake-ok", "gone-mod"]}
        assert cfg["ui"]["theme"] == "dark" and "# mine" in _file(served)
        assert served.hub.config.ui.nav.services == "counts"
        assert (await c.get("/api/settings")).json()["ui"]["nav"] == nav
        # a save without nav leaves it alone; the defaults remove the table
        await c.put("/api/settings", json={"ui": {"density": "comfortable"}})
        assert tomllib.loads(_file(served))["ui"]["nav"]["collapsed"] is True
        await c.put("/api/settings", json={"ui": {"nav": DEFAULT}})
        assert "nav" not in tomllib.loads(_file(served))["ui"]


async def test_bad_nav_values_are_refused(rig, serve):
    served = await _hub(rig, serve)
    async with httpx.AsyncClient(base_url=served.url) as c:
        for nav, field in (({**DEFAULT, "services": "tiles"}, "ui.nav.services"), ({**DEFAULT, "hidden": "fake-ok"}, "ui.nav.hidden"),
                           ({**DEFAULT, "extra": 1}, "ui.nav.extra")):
            r = await c.put("/api/settings", json={"ui": {"nav": nav}})
            assert r.status_code == 422 and r.json()["code"] == "invalid_config", nav
            assert r.json()["data"]["field"] == field
        assert "nav" not in _file(served)
