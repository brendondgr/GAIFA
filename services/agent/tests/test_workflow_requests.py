"""Plan agent-workflows 2.2: a sub-agent's cards go to the agent that started it: deny reaches the sub-agent with its
reason, forward leaves the card to the user, an unreviewed request is forwarded at the end of the parent's turn, the
parent can't approve, a background sub-agent's request starts the idle parent's turn, and an unattended one is refused."""

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


WIPER = {"name": "agent", "arguments": {"prompt": "wipe item a", "label": "Wiper", "write": True}}
WIPE = {"match": "wipe item a", "tool_calls": [{"name": "fake_wipe", "arguments": {"id": "a"}}]}


async def _needs_review(env, *after):
    env.model.queue({"match": "Clean up", "tool_calls": [WIPER]}, WIPE, *after)
    tid = await env.thread()
    await env.send(tid, "Clean up.")
    res = json.loads(env.payloads(tid, "tool_result")[0]["content"])
    return tid, res


async def test_deny_reaches_the_sub_agent(env):
    tid, res = await _needs_review(
        env, {"match": "needs_review", "tool_calls": [{"name": "agent_review", "arguments": {"action": "deny", "reason": "keep a"}}]},
        {"match": "said no: keep a", "text": "I didn't wipe it.", "delay": 0.5},     # after the parent's reply
        {"match": "agent_review", "text": "Denied it."},
        {"match": "you started in the background", "text": "It left a alone."})
    await _until(lambda: env.payloads(tid, "assistant") and env.payloads(tid, "assistant")[-1]["text"] == "It left a alone.")
    assert res["state"] == "needs_review" and res["requests"][0]["tool"] == "fake_wipe" and res["requests"][0]["risk"] == "destructive"
    assert res["requests"][0]["arguments"].startswith('<untrusted source="sub-agent Wiper request">')
    kid = res["child"]
    denied = env.payloads(kid, "tool_result")[0]
    assert denied["error"]["code"] == "denied_by_user" and "the chat that started you said no: keep a" in denied["error"]["detail"]
    assert env.hub.approvals["ap_1"]["state"] == "denied" and not env.hub.calls
    review = env.payloads(tid, "agent_review")[0]
    assert (review["action"], review["reason"], review["child"]) == ("deny", "keep a", kid)
    assert env.payloads(tid, "agent_done")[0]["answer"] == "I didn't wipe it."


async def test_forward_leaves_the_card_to_the_user(env):
    tid, res = await _needs_review(
        env, {"match": "needs_review", "tool_calls": [{"name": "agent_review", "arguments": {
            "action": "forward", "reason": "it's your data"}}]},
        {"match": "agent_review", "text": "It's up to you."},
        {"match": "you started in the background", "text": "a is gone."})
    kid = res["child"]
    assert json.loads(env.payloads(tid, "tool_result")[-1]["content"])["action"] == "forward"
    assert env.hub.approvals["ap_1"]["state"] == "pending" and env.agent.store.thread(kid)["state"] == "waiting"
    assert env.payloads(tid, "agent_review")[0]["action"] == "forward"
    r = await env.client.post(f"/v1/threads/{kid}/approval", json={"approval_id": "ap_1", "approve": True})
    assert r.status_code == 202, r.text
    await _until(lambda: env.payloads(tid, "assistant")[-1]["text"] == "a is gone.")
    assert [c["arguments"] for c in env.hub.calls] == [{"id": "a"}]


async def test_unreviewed_is_forwarded_and_approve_is_refused(env):
    tid, res = await _needs_review(
        env, {"match": "needs_review", "tool_calls": [{"name": "agent_review", "arguments": {"action": "approve"}}]},
        {"match": "can't approve", "text": "I'll leave it."})
    await env.settle(tid)
    err = env.payloads(tid, "tool_result")[-1]["error"]
    assert err["code"] == "invalid_request" and "can't approve" in err["detail"]
    [review] = env.payloads(tid, "agent_review")
    assert review["action"] == "forward" and review["auto"] is True and "didn't review" in review["reason"]
    assert env.hub.approvals["ap_1"]["state"] == "pending"


async def test_a_background_request_starts_the_parent(env):
    env.model.queue({"match": "Tidy", "tool_calls": [{**WIPER, "arguments": {**WIPER["arguments"], "background": True}}]},
                    {"match": "its answer arrives", "text": "Started."},
                    {**WIPE, "delay": 0.4},
                    {"match": "wants to run fake_wipe", "tool_calls": [{"name": "agent_review", "arguments": {"action": "deny"}}]},
                    {"match": "agent_review", "text": "Said no."})
    tid = await env.thread()
    await env.send(tid, "Tidy.")
    await _until(lambda: env.payloads(tid, "agent_review"))
    req = env.payloads(tid, "agent_request")[0]
    assert req["in_result"] is False and req["kind"] == "approval"
    msg = next(m for b in env.model.received for m in b["messages"] if "wants to run" in str(m.get("content")))
    assert msg["role"] == "user" and msg["content"].startswith("(From GAIFA, not the user")


async def test_agent_wait_returns_for_a_request(env):
    env.model.queue({"match": "Tidy up", "tool_calls": [{**WIPER, "arguments": {**WIPER["arguments"], "background": True}}]},
                    {"match": "its answer arrives", "tool_calls": [{"name": "agent_wait", "arguments": {}}]},
                    {**WIPE, "delay": 0.3},
                    {"match": "needs_review", "tool_calls": [{"name": "agent_review", "arguments": {"action": "forward"}}]},
                    {"match": "agent_review", "text": "Over to you."})
    tid = await env.thread()
    await env.send(tid, "Tidy up.")
    await _until(lambda: env.payloads(tid, "agent_review"), timeout=15)
    waited = json.loads(next(r for r in env.payloads(tid, "tool_result") if r["name"] == "agent_wait")["content"])
    assert waited["needs_review"][0]["tool"] == "fake_wipe" and "agent_review" in waited["note"]
    assert env.payloads(tid, "agent_review")[0]["action"] == "forward"


async def test_an_unattended_sub_agent_is_refused(env):
    env.model.queue({"match": "Clean up", "tool_calls": [WIPER]}, WIPE, {"match": "unattended", "text": "Couldn't."},
                    {"match": "Couldn't", "text": "Refused."})
    tid = await env.thread(settings={"unattended": True})
    await env.send(tid, "Clean up.")
    res = json.loads(env.payloads(tid, "tool_result")[0]["content"])
    assert res["state"] == "idle" and res["refused"] == ["fake_wipe"] and not env.payloads(tid, "agent_request")
