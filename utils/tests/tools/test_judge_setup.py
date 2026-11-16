"""capability-enablement 3.6: Auto's reason in words: the judge's status says "Decisions isn't set up on this machine"
with the setup fix when the decide mod was never set up, and "turned off" with Turn on when it's off."""

from __future__ import annotations

import httpx
import pytest

from utils import config
from utils.tests.tools.test_hub_tools import _copy


@pytest.fixture
def make(root, make_app):
    async def go(edits=None, cfg=""):
        _copy(root, "decide", edits)
        (root / "config.toml").write_text(cfg)
        app = make_app(config.load(root / "config.toml"), port=7000, autostart=False)
        return app
    return go


async def status(app):
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://hub") as c:
            return (await c.get("/api/judge/status")).json()


async def test_decide_not_set_up(make):
    s = await status(await make({"command": '[".venv/bin/python", "server.py"]'}))
    assert s["available"] is False and s["detail"] == "Decide isn't set up on this machine"
    assert s["fix"] == {"kind": "setup", "id": "decide", "command": "gaifa setup decide"}


async def test_decide_turned_off(make):
    s = await status(await make(cfg="[services.decide]\nenabled = false\n"))
    assert s["detail"] == "Decide is turned off" and s["fix"]["kind"] == "enable"


async def test_no_decide_mod(root, make_app):
    app = make_app(config.load(root / "config.toml"), port=7000, autostart=False)
    s = await status(app)
    assert s["fix"]["command"] == "gaifa setup decide"
