"""Plan agent-workflows 2.4: sub-agents never write memory or feed learning: no remember or agent_memory_* tools, the
memory routes refuse them, the learners skip them; a scheduled run's sub-agents run through the run's pre-allows."""

from __future__ import annotations

import asyncio
import json

import pytest


@pytest.fixture(autouse=True)
def _big_window(env):
    env.model.models["main"]["context_length"] = 32000


def _names(body):
    return {t["function"]["name"] for t in body.get("tools") or []}


async def test_no_memory_tools_and_the_routes_refuse(env):
    tid = await env.thread()
    kid = (await env.agent.workflows.spawn(tid, "look around", "Looker"))["id"]
    await env.agent.workflows.wait(kid, timeout=10)
    body = next(b for b in env.model.received if "look around" in json.dumps(b["messages"][1:]))
    assert "remember" not in _names(body) and "memory_search" in _names(body)
    from agent.tools import ToolSet
    ts = ToolSet(env.agent.hub, env.agent.store.thread(kid)["settings"])
    assert ts.off({"name": "agent_memory_save", "mod": "agent"}) and not ts.off({"name": "fake_get", "mod": "fake"})
    for path, body in (("/v1/memory/save", {"text": "The user likes tea."}), ("/v1/memory/entity", {"entity": "Tea", "kind": "topic"}),
                       ("/v1/memory/forget", {"fact": "f_1"})):
        r = await env.client.post(path, json=body, headers={"X-GAIFA-Origin": json.dumps({"service": "agent", "thread": kid})})
        assert r.status_code == 403 and r.json()["code"] == "sub_agent", (path, r.text)
    ok = await env.client.post("/v1/memory/save", json={"text": "The user likes tea."},
                               headers={"X-GAIFA-Origin": json.dumps({"service": "agent", "thread": tid})})
    assert ok.status_code == 200                                         # the chat that started it may


async def test_the_learners_skip_sub_agents(env):
    tid = await env.thread()
    kid = (await env.agent.workflows.spawn(tid, "say hello", "Greeter"))["id"]
    await env.agent.workflows.wait(kid, timeout=10)
    env.agent.store.append(kid, "feedback", {"value": "up", "note": ""})
    assert kid not in {e["thread_id"] for e in env.agent.store.events_by_type(["feedback", "user"])}   # the miner
    ml = env.agent.memory_learner
    ml.idle_s = 0
    assert kid not in {t["id"] for t in ml.due()}                         # the memory learner


async def test_a_scheduled_run_s_sub_agent_uses_its_pre_allows(env):
    env.model.queue({"match": "Weekly cleanup", "tool_calls": [{"name": "agent", "arguments": {
                        "prompt": "wipe item w", "label": "Wiper", "write": True}}]},
                    {"match": "wipe item w", "tool_calls": [{"name": "fake_wipe", "arguments": {"id": "w"}}]},
                    {"match": "Wiper", "text": "Cleaned."})
    r = await env.client.post("/v1/tasks", json={"name": "Weekly cleanup", "schedule": {"kind": "daily", "time": "07:00"},
                                                 "instructions": "Weekly cleanup.", "allow": {"tools": ["fake_wipe"]}})
    assert r.status_code == 201, r.text
    run = (await env.client.post(f"/v1/tasks/{r.json()['id']}/run")).json()
    for _ in range(200):
        run = env.agent.scheduled.run(run["id"])
        if run["state"] in ("done", "failed"):
            break
        await asyncio.sleep(0.05)
    assert run["state"] == "done", run
    [kid] = env.agent.store.children(run["thread_id"])
    assert kid["settings"]["unattended"] is True and "task_run" not in kid["settings"]
    assert [c["arguments"] for c in env.hub.calls if c["name"] == "fake_wipe"] == [{"id": "w"}]   # the run's grant covered it
    assert not env.payloads(run["thread_id"], "agent_request")
