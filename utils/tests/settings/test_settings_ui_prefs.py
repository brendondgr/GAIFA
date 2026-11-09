"""settings-that-stick 3.1: `[ui.chat]` and `[ui.overview]`: the UI's choices in config.toml, saved in part, written as
only what differs from the defaults, refused when unknown, and listed in the defaults."""

from __future__ import annotations

import tomllib

import httpx

from utils.tests.settings.test_settings import _file, _hub

CHAT = {"steps": "fold", "list": {"show": "chats", "group": "environment", "env_order": "activity", "chat_order": "updated", "collapsed": []}, "environment": None}
OVERVIEW = {"view": "dashboard", "timeline_range": "24h", "services_range": "24h"}


async def test_steps_round_trip(rig, serve):
    served = await _hub(rig, serve, "# mine\n[ui]\ntheme = \"dark\"\n")
    async with httpx.AsyncClient(base_url=served.url) as c:
        s = (await c.get("/api/settings")).json()["ui"]
        assert s["chat"] == CHAT and s["overview"] == OVERVIEW
        r = await c.put("/api/settings", json={"ui": {"chat": {"steps": "split"}}})
        assert r.status_code == 200 and r.json()["settings"]["ui"]["chat"] == {**CHAT, "steps": "split"}
        cfg = tomllib.loads(_file(served))
        assert cfg["ui"]["chat"] == {"steps": "split"} and cfg["ui"]["theme"] == "dark" and "# mine" in _file(served)
        # a part of the table changes only that part
        await c.put("/api/settings", json={"ui": {"chat": {"list": {"group": "none"}, "environment": "work"}}})
        cfg = tomllib.loads(_file(served))
        assert cfg["ui"]["chat"] == {"steps": "split", "list": {"group": "none"}, "environment": "work"}
        await c.put("/api/settings", json={"ui": {"overview": {"timeline_range": "7d"}}})
        assert tomllib.loads(_file(served))["ui"]["overview"] == {"timeline_range": "7d"}
        # back to the defaults removes the keys, then the table
        await c.put("/api/settings", json={"ui": {"chat": {"steps": "fold", "list": {"group": "environment"}, "environment": None}}})
        assert "chat" not in tomllib.loads(_file(served))["ui"]
        assert served.hub.config.ui.chat.steps == "fold"


async def test_bad_values_are_refused(rig, serve):
    served = await _hub(rig, serve)
    async with httpx.AsyncClient(base_url=served.url) as c:
        for ui, field in (({"chat": {"steps": "tiles"}}, "ui.chat.steps"), ({"overview": {"timeline_range": "2y"}}, "ui.overview.timeline_range"),
                          ({"chat": {"list": {"group": "x"}}}, "ui.chat.list.group"), ({"chat": {"extra": 1}}, "ui.chat.extra")):
            r = await c.put("/api/settings", json={"ui": ui})
            assert r.status_code == 422 and r.json()["code"] == "invalid_config", ui
            assert r.json()["data"]["field"] == field
        assert "chat" not in _file(served) and "overview" not in _file(served)


async def test_defaults_list_them(rig, serve):
    served = await _hub(rig, serve)
    async with httpx.AsyncClient(base_url=served.url) as c:
        d = (await c.get("/api/settings/defaults")).json()["ui"]
        assert d["chat"] == CHAT and d["overview"] == OVERVIEW


async def test_chat_list_show_and_date(rig, serve):
    """chat-history 2.2: `[ui.chat.list]` takes show (chats, archived, both) and group = "date"; anything else is refused."""
    served = await _hub(rig, serve)
    async with httpx.AsyncClient(base_url=served.url) as c:
        r = await c.put("/api/settings", json={"ui": {"chat": {"list": {"show": "both", "group": "date"}}}})
        assert r.status_code == 200 and r.json()["settings"]["ui"]["chat"]["list"] == {**CHAT["list"], "show": "both", "group": "date"}
        assert tomllib.loads(_file(served))["ui"]["chat"] == {"list": {"show": "both", "group": "date"}}
        for bad, field in (({"show": "all"}, "ui.chat.list.show"), ({"group": "project"}, "ui.chat.list.group")):
            r = await c.put("/api/settings", json={"ui": {"chat": {"list": bad}}})
            assert r.status_code == 422 and r.json()["data"]["field"] == field, r.text
