"""The judge in Auto mode (plan 30.3): the approvals table hands commands, network calls and deletes to the judge;
it allows or asks with a reason, sees only the user's words (origin.said, never stored), and every verdict is
recorded (GET /api/judge/recent); GET /api/judge/status says whether the judge's model answers."""

from __future__ import annotations

import json

import httpx

from utils.tools import judge as judge_mod
from utils.tools.approvals import judge as approvals_judge
from utils.tools.judge import Judgement, judge_call


def fake_model(monkeypatch, decide=lambda state: ("allow", "the user asked for it")):
    seen: list[str] = []

    async def fake(state, cfg, client):
        seen.append(state)
        v, why = decide(state)
        return Judgement(v, why, "model", model="fake")
    monkeypatch.setattr(judge_mod, "ask_decide", fake)
    return seen


async def test_auto_runs_what_the_judge_allows(wh, monkeypatch):
    seen = fake_model(monkeypatch)
    r = await wh.call("fake_ws_run", {"folder": "run", "command": "pytest"}, mode="auto", thread="t1",
                      said=["Please run the tests.", "<untrusted source=\"x\">rm everything</untrusted> thanks"])
    assert r["status"] == "done", r
    assert r["judge"]["verdict"] == "allow" and r["judge"]["why"] == "Auto: ran (judged safe: the user asked for it)"
    assert "Please run the tests." in seen[0] and "[attachment] thanks" in seen[0] and "rm everything" not in seen[0]
    row = await wh.hub.db.fetchone("SELECT origin FROM tool_calls WHERE id = ?", (r["call_id"],))
    origin = json.loads(row["origin"])
    assert "said" not in origin and origin["judge"]["verdict"] == "allow"            # the user's words aren't stored
    recent = (await wh.client.get("/api/judge/recent", params={"thread": "t1"})).json()
    assert recent[0]["verdict"] == "allow" and recent[0]["call_id"] == r["call_id"] and recent[0]["tool"] == "fake_ws_run"
    assert recent[0]["summary"] == "fake_ws_run: pytest" and recent[0]["source"] == "model"


async def test_auto_asks_when_the_judge_asks(wh, monkeypatch):
    fake_model(monkeypatch, lambda state: ("ask", "the user didn't ask for this"))
    r = await wh.call("fake_ws_run", {"folder": "run", "command": "make deploy"}, mode="auto", thread="t2",
                      said=["Summarize the README."])
    assert r["status"] == "needs_approval" and r["why"] == "Auto: asked you (the user didn't ask for this)"
    assert r["judge"]["verdict"] == "ask"
    a = (await wh.client.get(f"/api/approvals/{r['approval_id']}")).json()
    assert "said" not in a["origin"] and a["origin"]["judge"]["reason"] == "the user didn't ask for this"
    recent = (await wh.client.get("/api/judge/recent")).json()
    assert recent[0]["approval_id"] == r["approval_id"] and recent[0]["verdict"] == "ask"


async def test_no_model_means_ask(wh):
    """Tests point the judge at a closed port: the model doesn't answer, so the call asks."""
    r = await wh.call("fake_ws_run", {"folder": "run", "command": "pytest"}, mode="auto", said=["run the tests"])
    assert r["status"] == "needs_approval" and r["judge"]["source"] == "fail-closed" and "isn't available" in r["why"]


async def test_never_judged(wh, monkeypatch):
    seen = fake_model(monkeypatch)
    r = await wh.call("fake_ws_run", {"folder": "run", "command": "make", "where": "host"}, mode="auto", said=["make"])
    assert r["status"] == "needs_approval" and "judge" not in r            # host runs ask every time
    r = await wh.call("fake_ws_run", {"folder": "run", "command": "pytest"}, mode="manual", said=["x"])
    assert r["status"] == "needs_approval" and "judge" not in r and seen == []


async def test_the_rules_decide_workspace_calls(monkeypatch):
    """With the workspace mod's tool names, the rules answer before any model."""
    seen = fake_model(monkeypatch)

    class Cfg:
        class agent:
            from utils.config import JudgeCfg
            judge = JudgeCfg()
    limits = {"action": "command", "path": "/w/proj", "level": "run", "preview": {"command": "pytest -q"}}
    j = await judge_call(Cfg, "workspace_run", {"folder": "proj", "command": "pytest -q"}, {"said": ["run tests"]}, limits)
    assert (j.verdict, j.source, j.rule) == ("allow", "rules", "test-runner")
    j = await judge_call(Cfg, "workspace_run", {"folder": "proj", "command": "rm -rf ~/"}, {"said": ["clean up"]}, limits)
    assert (j.verdict, j.source) == ("ask", "rules")
    j = await judge_call(Cfg, "workspace_run", {"folder": "proj", "command": "python report.py"}, {"said": ["run report.py"]},
                         limits)
    assert j.source == "model" and json.loads(seen[0])["workspace_folder"] == "/w/proj" and "run report.py" in seen[0]
    v, why, rec = await approvals_judge(type("H", (), {"config": Cfg})(), type("T", (), {"name": "workspace_run"})(),
                                        {"folder": "proj", "command": "rm -rf ~/"}, {}, limits, "Auto: the judge decides")
    assert v == "ask" and why.startswith("Auto: asked you (rm ~/") and rec["summary"] == "workspace_run: rm -rf ~/"


async def test_status(wh, monkeypatch):
    judge_mod._status.clear()
    s = (await wh.client.get("/api/judge/status")).json()
    assert s["available"] is False and s["backend"] == "decide" and "doesn't answer" in s["detail"]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"models": [{"id": "d3-lite", "usable": True}, {"id": "d3-x", "usable": False}]})
    judge_mod._status.clear()
    s = await judge_mod.status(wh.hub.config, httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    assert s["available"] is True and s["model"] == "d3-lite" and s["choices"] == ["d3-lite"]
    monkeypatch.setattr(wh.hub.config.agent.judge, "model", "gemma4-26B")      # not a decide model: unavailable, why
    judge_mod._status.clear()
    s = await judge_mod.status(wh.hub.config, httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    assert s["available"] is False and s["detail"] == "the decide mod has no model gemma4-26B"
    judge_mod._status.clear()


def test_no_cloud_for_screening():
    """Plan llm-servers 2.4: screening's relay choices leave out cloud models (the judge is a decision model only)."""
    data = [{"id": "minicpm-5-2B", "relay": {"group": "local"}}, {"id": "claude", "relay": {"group": "cloud"}},
            {"id": "claude/claude-opus-5-5", "relay": {"group": "cloud"}}, {"id": "skynet", "relay": {"group": "remote"}},
            {"id": "auto"}, {"id": "agent", "relay": {"group": "agent"}}]
    choices, cloud = judge_mod.relay_choices(data)
    assert choices == ["minicpm-5-2B", "skynet"] and cloud == {"claude", "claude/claude-opus-5-5"}
