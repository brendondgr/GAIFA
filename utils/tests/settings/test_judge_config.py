"""web-approvals 1.1: the Auto judge is only ever a decision model (the decide mod, d3-lite), never a chat model.

2026-11-08: `[agent.judge]` named gemma4-26B through the relay; lcpp was stopped, so every judgement was a 404 and
asked, and when it ran it took seconds per link. An old config.toml still loads, as the decide defaults."""

from __future__ import annotations

import tomllib

import httpx

from utils.config import JUDGE_DECIDE, JudgeCfg, validate
from utils.doctor import _judge
from utils.tests.settings.test_settings import _file, _hub


def test_the_default_judge_is_d3_lite_in_the_decide_mod():
    j = JudgeCfg()
    assert (j.backend, j.model, j.url) == ("decide", "d3-lite", "http://127.0.0.1:7000/api/s/decide")


def test_a_chat_model_judge_in_config_toml_is_read_as_the_decide_defaults():
    cfg = validate({"agent": {"judge": {"backend": "relay", "model": "gemma4-26B", "url": "http://127.0.0.1:4000",
                                        "context": "full", "threshold": 0.4}}})
    j = cfg.agent.judge
    assert {k: getattr(j, k) for k in JUDGE_DECIDE} == JUDGE_DECIDE
    assert (j.context, j.threshold) == ("full", 0.4)          # the rest of the table is kept


async def test_settings_refuse_a_chat_model_judge(rig, serve):
    served = await _hub(rig, serve, "")
    async with httpx.AsyncClient(base_url=served.url) as c:
        r = await c.put("/api/settings", json={"judge": {"backend": "relay", "model": "gemma4-26B"}})
        assert r.status_code == 422 and r.json()["data"]["field"].startswith("judge.backend"), r.text
        assert served.hub.config.agent.judge.model == "d3-lite"
        assert "judge" not in (tomllib.loads(_file(served)).get("agent") or {})


async def test_the_doctor_names_a_stale_chat_model_judge(rig, serve):
    served = await _hub(rig, serve, '[agent.judge]\nbackend = "relay"\nmodel = "gemma4-26B"\n')
    assert served.hub.config.agent.judge.model == "d3-lite"
    (c,) = _judge(served.hub)
    assert c["level"] == "warn" and "gemma4-26B" in c["detail"] and "d3-lite" in c["detail"]
    served.hub.paths.config_file.write_text('[agent.judge]\nmodel = "d3-lite"\n')
    assert _judge(served.hub) == []
