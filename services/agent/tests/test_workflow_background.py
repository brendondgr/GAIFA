"""Plan agent-workflows 2.1: background sub-agents: their end starts an idle parent's turn as a message from GAIFA;
agent_wait returns one instead; agent_send gives one more to do; agent_stop and Stop on the parent report nothing."""

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


def _bg(prompt, label="Helper"):
    return {"name": "agent", "arguments": {"prompt": prompt, "label": label, "background": True}}


async def test_an_idle_parent_reads_the_end(env):
    env.model.queue({"match": "Check the logs", "tool_calls": [_bg("count the errors in the logs")]},
                    {"match": "its answer arrives", "text": "Started a helper; I'll tell you."},
                    {"match": "count the errors", "text": "There are 3 errors.", "delay": 0.4},
                    {"match": "you started in the background finished", "text": "The helper found 3 errors."})
    tid = await env.thread()
    await env.send(tid, "Check the logs.")
    res = json.loads(env.payloads(tid, "tool_result")[0]["content"])
    assert res["background"] is True and res["child"].startswith("t_")
    assert env.payloads(tid, "assistant")[-1]["text"] == "Started a helper; I'll tell you."
    await _until(lambda: len(env.payloads(tid, "assistant")) == 2)
    await env.settle(tid)
    done = env.payloads(tid, "agent_done")[0]
    assert done["label"] == "Helper" and done["answer"] == "There are 3 errors." and done["chat"] == f"#/chat/{res['child']}"
    assert env.payloads(tid, "assistant")[-1]["text"] == "The helper found 3 errors."
    msg = env.model.received[-1]["messages"][-1]
    assert msg["role"] == "user" and msg["content"].startswith("(From GAIFA, not the user")
    assert env.agent.store.thread(res["child"])["spawn"]["reported"] is True


async def test_agent_wait_returns_it_instead(env):
    env.model.queue({"match": "Two jobs", "tool_calls": [_bg("job one please", "One"), _bg("job two please", "Two")]},
                    {"match": "its answer arrives", "tool_calls": [{"name": "agent_wait", "arguments": {}}]},
                    {"match": "job one please", "text": "one done", "delay": 0.4},       # after agent_wait began
                    {"match": "job two please", "text": "two done", "delay": 0.5},
                    {"match": "still_running", "tool_calls": [{"name": "agent_wait", "arguments": {}}]},
                    {"match": "two done", "text": "Both done."})
    tid = await env.thread()
    await env.send(tid, "Two jobs.")
    await _until(lambda: env.payloads(tid, "assistant") and env.payloads(tid, "assistant")[-1]["text"] == "Both done.")
    await env.settle(tid)
    waits = [json.loads(r["content"]) for r in env.payloads(tid, "tool_result") if r["name"] == "agent_wait"]
    assert [w["answer"] for w in waits] == ["one done", "two done"] and waits[0]["still_running"] == ["Two"]
    assert env.payloads(tid, "agent_done") == []                          # both came back through agent_wait


async def test_wait_with_nothing_to_wait_for(env):
    env.model.queue({"match": "Wait", "tool_calls": [{"name": "agent_wait", "arguments": {}}]}, {"text": "Nothing."})
    tid = await env.thread()
    await env.send(tid, "Wait.")
    assert env.payloads(tid, "tool_result")[0]["error"]["code"] == "nothing_to_wait_for"
    kid = (await env.agent.workflows.spawn(tid, "a quick one", "Quick", background=True))["id"]
    await _until(lambda: env.payloads(tid, "agent_done"))
    await env.settle(tid)
    env.model.queue({"match": "Wait for it", "tool_calls": [{"name": "agent_wait", "arguments": {"child": kid}}]}, {"text": "Got it."})
    await env.send(tid, "Wait for it.")
    got = json.loads(env.payloads(tid, "tool_result")[-1]["content"])      # reported as a message already: given again
    assert got["child"] == kid and "reported already" in got["note"]


async def test_agent_send_gives_a_finished_one_more_to_do(env):
    wf = env.agent.workflows
    tid = await env.thread()
    kid = (await wf.spawn(tid, "list the files", "Lister"))["id"]
    await wf.wait(kid, timeout=10)
    env.model.queue({"match": "And the folders", "tool_calls": [{"name": "agent_send", "arguments": {
                        "child": kid, "text": "now list the folders too"}}]},
                    {"match": "its answer arrives", "text": "Asked it."},
                    {"match": "now list the folders too", "text": "folders: a, b", "delay": 0.5},   # after the parent's reply
                    {"match": "folders: a, b", "text": "It says: a, b."})
    await env.send(tid, "And the folders?")
    await _until(lambda: env.payloads(tid, "assistant")[-1]["text"] == "It says: a, b.")
    assert [u["text"] for u in env.payloads(kid, "user")] == ["list the files", "now list the folders too"]
    assert env.payloads(tid, "agent_done")[0]["answer"] == "folders: a, b"
    env.model.queue({"match": "Bad send", "tool_calls": [{"name": "agent_send", "arguments": {"child": "t_nope", "text": "x"}}]},
                    {"text": "ok"})
    await env.send(tid, "Bad send.")
    assert env.payloads(tid, "tool_result")[-1]["error"]["code"] == "unknown_child"


async def test_stopping_reports_nothing(env):
    env.model.queue({"match": "Slow one", "tool_calls": [_bg("the slow task")]},
                    {"match": "its answer arrives", "text": "Started."},
                    {"match": "the slow task", "text": "late", "delay": 5})
    tid = await env.thread()
    await env.send(tid, "Slow one.")
    [kid] = [c["id"] for c in env.agent.store.children(tid)]
    await _until(lambda: env.agent.running(kid))
    env.model.queue({"match": "Stop it", "tool_calls": [{"name": "agent_stop", "arguments": {"child": kid}}]},
                    {"match": "agent_stop", "text": "Stopped."})
    await env.send(tid, "Stop it.")
    await _until(lambda: not env.agent.running(kid))
    await env.settle(tid)
    assert json.loads(env.payloads(tid, "tool_result")[-1]["content"])["state"] == "idle"
    assert env.payloads(tid, "agent_done") == [] and env.payloads(tid, "assistant")[-1]["text"] == "Stopped."
    env.model.queue({"match": "Another", "tool_calls": [_bg("another slow task", "Two")]},
                    {"match": "its answer arrives", "text": "Started two."},
                    {"match": "another slow task", "text": "late", "delay": 5})
    await env.send(tid, "Another.")
    two = next(c["id"] for c in env.agent.store.children(tid) if c["title"] == "Two")
    await _until(lambda: env.agent.running(two))
    await env.client.post(f"/v1/threads/{tid}/cancel")                   # Stop on the parent
    await _until(lambda: not env.agent.running(two))
    await asyncio.sleep(0.3)
    assert env.payloads(tid, "agent_done") == [] and not env.agent.running(tid)
