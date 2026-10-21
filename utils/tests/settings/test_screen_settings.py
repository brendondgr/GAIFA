"""Plan 30.8: the screening model is set in Settings (`[agent.screen] backend/model/url/threshold/confirm`), saved
under [agent.screen], and unset again (back to the judge's) by sending null."""

from __future__ import annotations

import tomllib

import httpx

from utils.tests.settings.test_settings import _file, _hub
from utils.tools.screen import screen_config


async def test_a_screening_model_of_its_own(rig, serve):
    served = await _hub(rig, serve, "")
    async with httpx.AsyncClient(base_url=served.url) as c:
        r = await c.put("/api/settings", json={"screen": {"backend": "decide", "threshold": 0.9}})
        assert r.status_code == 200, r.text
        assert r.json()["settings"]["screen"]["backend"] == "decide"
        assert tomllib.loads(_file(served))["agent"]["screen"] == {"backend": "decide", "threshold": 0.9}
        s = screen_config(served.hub.config)                   # applies at once; the judge stays as it was
        assert (s.backend, s.model, s.threshold) == ("decide", "d3-lite", 0.9) and served.hub.config.agent.judge.backend == "relay"
        r = await c.put("/api/settings", json={"screen": {"backend": "nope"}})
        assert r.status_code == 422 and r.json()["data"]["field"].startswith("screen")
        r = await c.put("/api/settings", json={"screen": {"backend": None, "threshold": None}})
        assert r.status_code == 200 and "screen" not in (tomllib.loads(_file(served)).get("agent") or {})
        assert screen_config(served.hub.config).backend == "relay"
