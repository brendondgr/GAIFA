"""settings-that-stick 2.3: a save publishes `{type: "settings", changed}` so every open page reloads."""

from __future__ import annotations

import asyncio

import httpx

from utils.settings import changed_keys
from utils.tests.settings.test_settings import _hub


def test_changed_keys():
    before = {"judge": {"allow_commands": ["a"], "threshold": 0.35}, "ui": {"nav": {"folded": False}}}
    after = {"judge": {"allow_commands": ["a", "b"], "threshold": 0.35}, "ui": {"nav": {"folded": True}}}
    assert changed_keys(before, after) == ["judge.allow_commands", "ui.nav"]


async def _settings_events(served, act) -> list[dict]:
    sub = served.hub.bus.subscribe()
    try:
        await act()
        out = []
        while True:
            try:
                ev = await asyncio.wait_for(sub.get(), 0.2)
            except TimeoutError:
                return out
            if ev.get("type") == "settings":
                out.append(ev)
    finally:
        sub.close()


async def test_a_save_publishes_what_changed(rig, serve):
    served = await _hub(rig, serve)
    async with httpx.AsyncClient(base_url=served.url) as c:
        evs = await _settings_events(served, lambda: c.put("/api/settings", json={"judge": {"allow_commands": ["ls"]}, "ui": {"density": "comfortable"}}))
        assert evs == [{"type": "settings", "changed": ["ui.density", "judge.allow_commands"]}]
        # an unchanged save publishes nothing
        assert await _settings_events(served, lambda: c.put("/api/settings", json={"judge": {"allow_commands": ["ls"]}})) == []
        # a mod's own settings that show in Settings (its switches) do too
        evs = await _settings_events(served, lambda: c.put("/api/services/fake-ok/config", json={"autostart": False}))
        assert evs == [{"type": "settings", "changed": ["services.autostart"]}]
