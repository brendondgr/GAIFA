"""settings-that-stick 1.2 / 2.1: a save never drops what another writer saved since it loaded.

Each writer sends `base`, the value a changed key had when it loaded the settings; lists merge (what the writer
added and removed), so a command rule added elsewhere survives the Settings page saving its own edit."""

from __future__ import annotations

import asyncio
import tomllib

import httpx
import pytest

from utils.tests.settings.test_settings import _file, _hub


@pytest.mark.xfail(strict=True, reason="settings-that-stick 2.1: `base` and the merge")
async def test_a_list_keeps_what_another_save_added(rig, serve):
    served = await _hub(rig, serve, '[agent.judge]\nallow_commands = ["git status"]\n')
    async with httpx.AsyncClient(base_url=served.url) as c:
        # a chat's "Always allow" adds a rule …
        r = await c.put("/api/settings", json={"judge": {"allow_commands": ["git status", "ls"]},
                                               "base": {"judge": {"allow_commands": ["git status"]}}})
        assert r.status_code == 200, r.text
        # … then the Settings page, loaded before it, saves its own addition
        r = await c.put("/api/settings", json={"judge": {"allow_commands": ["git status", "pytest *"]},
                                               "base": {"judge": {"allow_commands": ["git status"]}}})
        assert r.status_code == 200, r.text
        assert r.json()["settings"]["judge"]["allow_commands"] == ["git status", "ls", "pytest *"]
        assert tomllib.loads(_file(served))["agent"]["judge"]["allow_commands"] == ["git status", "ls", "pytest *"]


async def test_two_saves_at_once_both_land(rig, serve):
    served = await _hub(rig, serve)
    async with httpx.AsyncClient(base_url=served.url) as c:
        a, b = await asyncio.gather(c.put("/api/settings", json={"ui": {"density": "comfortable"}}),
                                    c.put("/api/settings", json={"judge": {"ask_commands": ["git push"]}}))
        assert a.status_code == b.status_code == 200
        cfg = tomllib.loads(_file(served))
        assert cfg["ui"]["density"] == "comfortable" and cfg["agent"]["judge"]["ask_commands"] == ["git push"]
