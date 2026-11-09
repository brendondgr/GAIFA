"""Reading web pages in Settings → Agent: `[agent.web]` (a long page's relevant passages first), `[agent.screen]
parallel` and `[outputs] hidden_keep_days` (the saved pages' clean-up) are saved, validated and applied at once;
`GET /api/web/reading` says which model screens and what relevance uses now."""

from __future__ import annotations

import tomllib

import httpx

from utils.tests.settings.test_settings import _file, _hub


async def test_relevance_cleanup_and_parallel_are_saved_and_validated(rig, serve):
    served = await _hub(rig, serve, "[outputs]\nhidden_keep_days = 2   # keep this comment\n")
    async with httpx.AsyncClient(base_url=served.url) as c:
        s = (await c.get("/api/settings")).json()
        assert s["outputs"] == {"hidden_keep_days": 2} and s["web"]["relevance"] == "auto" and s["screen"]["parallel"] == 4
        r = await c.put("/api/settings", json={"web": {"relevance": "lexical"}, "outputs": {"hidden_keep_days": 7},
                                               "screen": {"parallel": 8}})
        assert r.status_code == 200, r.text
        saved = tomllib.loads(_file(served))
        assert saved["agent"]["web"] == {"relevance": "lexical"} and saved["agent"]["screen"] == {"parallel": 8}
        assert saved["outputs"] == {"hidden_keep_days": 7} and "keep this comment" in _file(served)
        cfg = served.hub.config                                  # applies at once
        assert cfg.agent.web.relevance == "lexical" and cfg.outputs.hidden_keep_days == 7 and cfg.agent.screen.parallel == 8
        for bad in ({"web": {"relevance": "psychic"}}, {"outputs": {"hidden_keep_days": -1}}, {"screen": {"parallel": 0}},
                    {"web": {"candidates": 1}}):
            r = await c.put("/api/settings", json=bad)
            assert r.status_code == 422 and r.json()["code"] == "invalid_config", (bad, r.text)
            assert r.json()["data"]["field"].startswith(next(iter(bad))), r.json()
        r = await c.put("/api/settings", json={"web": {"relevance": "auto"}, "outputs": {"hidden_keep_days": 0}})
        assert r.status_code == 200
        saved = tomllib.loads(_file(served))
        assert "web" not in saved.get("agent", {}) and "hidden_keep_days" not in saved.get("outputs", {})   # defaults: removed


async def test_the_reading_route_says_what_screens_and_ranks(rig, serve):
    served = await _hub(rig, serve, "")
    async with httpx.AsyncClient(base_url=served.url) as c:
        r = await c.get("/api/web/reading")
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["screen"] == {"backend": "decide", "model": "d3-lite", "confirm": None, "same_as_judge": True}
        assert d["judge"] == {"backend": "decide", "model": "d3-lite"}      # always a decision model (web-approvals)
        assert d["relevance"] == "lexical" and d["decide_up"] is False and d["choices"]["decide"] == []
        await c.put("/api/settings", json={"screen": {"backend": "relay", "model": "minicpm-5-2B"}})
        d = (await c.get("/api/web/reading")).json()
        assert d["screen"]["backend"] == "relay" and d["screen"]["model"] == "minicpm-5-2B"
        assert d["screen"]["confirm"] is None and d["screen"]["same_as_judge"] is False
