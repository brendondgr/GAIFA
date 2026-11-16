"""capability-enablement 4.1: the hub's setup tools: the plan's text; hub_setup asks (a card) and, approved, follows the
job to its report with a fake gaifa; needs_you comes back as what the user must run; refused in an unattended run;
absent from /mcp; hub_setup_test says what it measured."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from utils import config
from utils.tests.routes.test_setup_jobs import PLAN, FakeGaifa, _fresh
from utils.tools.hub_setup_tools import plan_text


@pytest.fixture
async def hub(root, make_app):
    _fresh(root)
    fake = FakeGaifa()
    app = make_app(config.load(root / "config.toml"), port=7000, autostart=False, setup_runner=fake)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://hub", timeout=60) as c:
            yield app, c, fake


async def call(c, name, args, mode="manual", **origin):
    r = await c.post(f"/api/tools/{name}/call?wait=30", json={"arguments": args, "mode": mode, "origin": origin})
    assert r.status_code == 200, r.text
    return r.json()


def test_the_plan_in_words():
    plan = {**PLAN, "about": [{"id": "fresh", "name": "Fresh", "provides": "make fake things", "folder": "services/fresh", "port": 5150}],
            "suggestions": [{"name": "d3-lite", "size_gb": 1.73, "source": "vllm-sr/d3-lite", "licence": "Apache-2.0", "required": True}],
            "questions": [{"id": "fresh/models", "text": "Which models?", "choices": ["d3-lite"]}],
            "host": [{"id": "podman", "ok": False, "detail": "podman is missing", "fix": "sudo dnf install podman", "needs_root": True}]}
    t = plan_text(plan)
    assert "Fresh (fresh): make fake things. It goes in services/fresh and listens on 127.0.0.1:5150." in t
    assert "Step fresh/1: makes .venv/ (70 MB)." in t
    assert "Download d3-lite: 1.7 GB from vllm-sr/d3-lite, licence Apache-2.0 (needed)." in t
    assert "Question fresh/models: Which models? (choices: d3-lite)." in t
    assert "Fix first: podman is missing: sudo dnf install podman (needs sudo: the person runs it)." in t


async def test_plan_tool(hub):
    app, c, fake = hub
    out = await call(c, "hub_setup_plan", {"ids": ["fresh"]})
    assert out["status"] == "done" and "Step fresh/1: makes .venv/ (70 MB)." in out["result"]["text"]


async def test_setup_asks_then_runs_to_its_report(hub):
    app, c, fake = hub
    out = await call(c, "hub_setup", {"ids": ["fresh"], "answers": {"models": {"fresh": ["none"]}}}, mode="bypass")
    assert out["status"] == "needs_approval", out                       # the ask list: a card even in Bypass
    r = await c.post(f"/api/approvals/{out['approval_id']}?wait=30", json={"approve": True})
    res = r.json()
    for _ in range(60):
        if res.get("status") != "running":
            break
        res = (await c.get(f"/api/tools/calls/{res['call_id']}?wait=5")).json()
    assert res["status"] == "done", res
    assert res["result"]["state"] == "done" and res["result"]["started"] == [{"id": "fresh", "state": "ready"}]
    assert fake.answers[-1] == {"yes": True, "models": {"fresh": ["none"]}}
    await app.state.hub.services.stop("fresh", wait=True)


async def test_needs_you_comes_back_as_what_to_run(hub):
    app, c, fake = hub
    fake.rc = 2
    res = await app.state.hub.calls.call("hub_setup", {"ids": ["fresh"]}, {}, mode="manual")
    r = await c.post(f"/api/approvals/{res['approval_id']}?wait=30", json={"approve": True})
    out = r.json()
    for _ in range(60):
        if out.get("status") != "running":
            break
        out = (await c.get(f"/api/tools/calls/{out['call_id']}?wait=5")).json()
    assert out["result"]["state"] == "needs_you" and out["result"]["questions"][0]["id"] == "fresh/licence"


async def test_refused_unattended_and_absent_from_mcp(hub):
    app, c, fake = hub
    out = await call(c, "hub_setup", {"ids": ["fresh"]}, mode="auto", unattended=True)
    assert out["status"] == "denied" and out["error"]["code"] == "unattended"
    r = await c.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                     headers={"Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2025-06-18"})
    names = {t["name"] for t in r.json()["result"]["tools"]}
    assert "hub_setup" not in names and "hub_setup_plan" in names


async def test_the_test_tool(hub):
    app, c, fake = hub
    out = await call(c, "hub_setup_test", {"id": "fresh"})
    assert out["status"] == "done" and out["result"]["passed"] is True and set(out["result"]) == {"id", "passed", "seconds", "device", "log"}


async def test_a_mod_not_set_up_now_names_hub_setup(hub):
    app, c, fake = hub
    tools = {t["name"]: t for t in (await c.get("/api/tools")).json()}
    svc = (await c.get("/api/services/fresh")).json()
    assert svc["availability"]["fix"]["tool"] == "hub_setup"
