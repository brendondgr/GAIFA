"""Plan agent-workflows 2.3: deciding a sub-agent's request from the chat that started it: the approval runs the
sub-agent's call; remembered, it covers another sub-agent's same call; the list shows what waits; a decided one is 409."""

from __future__ import annotations

import asyncio
import json

import pytest


@pytest.fixture(autouse=True)
def _big_window(env):
    env.model.models["main"]["context_length"] = 32000


async def _until(cond, timeout=10):
    for _ in range(int(timeout / 0.05)):
        if cond():
            return
        await asyncio.sleep(0.05)
    raise TimeoutError


def _wiper(item, label):
    return {"name": "agent", "arguments": {"prompt": f"wipe item {item}", "label": label, "write": True, "background": True}}


async def test_approve_from_the_parent_and_remember_for_the_workflow(env):
    env.model.queue({"match": "Clean a", "tool_calls": [_wiper("a", "First")]},
                    {"match": "its answer arrives", "text": "Started."},
                    {"match": "wipe item a", "tool_calls": [{"name": "fake_wipe", "arguments": {"id": "a"}}], "delay": 0.3},
                    {"match": "wants to run fake_wipe", "tool_calls": [{"name": "agent_review", "arguments": {
                        "action": "forward", "reason": "your call"}}]},
                    {"match": "agent_review", "text": "Over to you."})
    tid = await env.thread()
    await env.send(tid, "Clean a.")
    await _until(lambda: env.payloads(tid, "agent_review"))
    await env.settle(tid)
    r = await env.client.get(f"/v1/threads/{tid}/requests?waiting=true")
    [req] = r.json()
    assert req["tool"] == "fake_wipe" and req["waiting"] and not req["open"] and req["review"]["action"] == "forward"
    r = await env.client.post(f"/v1/threads/{tid}/requests/{req['id']}", json={"approve": True, "remember": "thread"})
    assert r.status_code == 202, r.text
    assert r.json()["action"] == "approve"
    await _until(lambda: [c["arguments"] for c in env.hub.calls] == [{"id": "a"}])
    assert env.hub.grants[-1]["thread"] == tid                       # written for the workflow's root
    assert (await env.client.get(f"/v1/threads/{tid}/requests?waiting=true")).json() == []
    again = await env.client.post(f"/v1/threads/{tid}/requests/{req['id']}", json={"approve": True})
    assert again.status_code == 409
    env.model.queue({"match": "Clean b", "tool_calls": [_wiper("b", "Second")]},
                    {"match": "Clean b", "text": "Started the second."},
                    {"match": "wipe item b", "tool_calls": [{"name": "fake_wipe", "arguments": {"id": "b"}}]})
    await env.send(tid, "Clean b.")
    await _until(lambda: {"id": "b"} in [c["arguments"] for c in env.hub.calls])       # no card this time
    assert len(env.payloads(tid, "agent_request")) == 1


async def test_deny_from_the_parent(env):
    store = env.agent.store
    tid = await env.thread()
    env.model.queue({"match": "wipe item c", "tool_calls": [{"name": "fake_wipe", "arguments": {"id": "c"}}]},
                    {"match": "denied", "text": "Left c."})
    kid = (await env.agent.workflows.spawn(tid, "wipe item c", "Third", write=True, background=True))["id"]
    await _until(lambda: env.payloads(tid, "agent_request"))
    rid = env.payloads(tid, "agent_request")[0]["id"]
    assert (await env.client.post(f"/v1/threads/{tid}/requests/rq_nope", json={})).status_code == 404
    r = await env.client.post(f"/v1/threads/{tid}/requests/{rid}", json={"approve": False, "reason": "not today"})
    assert r.status_code == 202 and r.json()["action"] == "deny"
    await _until(lambda: store.thread(kid)["state"] == "idle" and not env.agent.running(kid))
    assert env.payloads(kid, "tool_result")[0]["error"]["detail"].endswith("not today")
    assert env.payloads(tid, "agent_review")[-1]["by"] == "user" and not env.hub.calls
