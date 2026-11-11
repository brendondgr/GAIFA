"""Plan voice-speech-model 3.1: [voice_mode], what answers in Chat's voice mode."""

from __future__ import annotations

import tomllib

import httpx

from utils.config import VoiceModeCfg
from utils.tests.settings.test_settings import _file


def test_defaults():
    assert VoiceModeCfg().model_dump() == {"engine": "chat", "quant": "q4_k_m", "voice": "female", "tools": [], "ask_chat": False}


async def test_saved_in_config_toml(rig, serve):
    served = await serve()
    async with httpx.AsyncClient(base_url=served.url) as c:
        assert (await c.get("/api/settings")).json()["voice_mode"]["engine"] == "chat"
        r = await c.put("/api/settings", json={"voice_mode": {"engine": "speech", "quant": "q8_0"}})
        assert r.status_code == 200, r.text
        assert r.json()["settings"]["voice_mode"] == {"engine": "speech", "quant": "q8_0", "voice": "female", "tools": [],
                                                      "ask_chat": False}
        assert tomllib.loads(_file(served))["voice_mode"] == {"engine": "speech", "quant": "q8_0"}
        assert served.hub.config.voice_mode.engine == "speech"
        for bad in ({"engine": "robot"}, {"quant": "q2"}, {"voice": "alto"}, {"tools": ["Bad Name"]},
                    {"tools": [f"t_{i}" for i in range(7)]}):
            assert (await c.put("/api/settings", json={"voice_mode": bad})).status_code == 422, bad
        r = await c.put("/api/settings", json={"voice_mode": {"tools": ["calendar_agenda", "calendar_agenda"], "voice": "male"}})
        assert r.json()["settings"]["voice_mode"]["tools"] == ["calendar_agenda"]
        await c.put("/api/settings", json={"voice_mode": {"engine": "chat", "quant": "q4_k_m", "voice": "female", "tools": []}})
        assert "voice_mode" not in tomllib.loads(_file(served))                # defaults leave the file alone


async def test_a_save_merges_with_another_pages(rig, serve):
    """settings-that-stick: a page that loaded before another save doesn't undo it."""
    served = await serve()
    async with httpx.AsyncClient(base_url=served.url) as c:
        base = (await c.get("/api/settings")).json()
        await c.put("/api/settings", json={"voice_mode": {"voice": "male"}})
        r = await c.put("/api/settings", json={"voice_mode": {**base["voice_mode"], "engine": "speech"}, "base": {"voice_mode": base["voice_mode"]}})
        assert r.status_code == 200, r.text
        assert r.json()["settings"]["voice_mode"]["voice"] == "male" and r.json()["settings"]["voice_mode"]["engine"] == "speech"
