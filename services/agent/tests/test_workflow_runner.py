"""Plan agent-workflows 1.2: the runner: what a sub-agent takes from its parent, the queue and its slots, the limits,
the token budget, results, and stopping with the parent."""

from __future__ import annotations

import asyncio

import pytest

from agent.workflows.runner import ANSWER_CHARS, WorkflowError


def _parent(env, **settings):
    return env.agent.store.create_thread("Main", "main", "auto", {"environment": "e1", "disabled": ["comfy"],
                                                                   "task": "k1", "task_run": "r1", **settings})


async def _done(env, tid, timeout=10):
    r = await env.agent.workflows.wait(tid, timeout=timeout)
    assert r is not None, env.types(tid)
    return r


async def test_a_sub_agent_s_settings(env):
    wf = env.agent.workflows
    p = _parent(env, unattended=True)
    c = await wf.spawn(p["id"], "Read the folder and list its files.", "Folder reader")
    s = c["settings"]
    assert s["environment"] == "e1" and s["disabled"] == ["comfy"] and s["unattended"] is True and s["no_learn"] is True
    assert "task" not in s and "task_run" not in s and s["max_steps"] == 25
    assert s["spawn"] == {"root": p["id"], "parent": p["id"], "label": "Folder reader", "by": "agent", "tool_call_id": None,
                          "write": False, "depth": 1, "turn": 0, "seen": True}
    assert c["model"] == "main" and c["mode"] == "auto" and c["title"] == "Folder reader" and c["parent_id"] == p["id"]
    r = await _done(env, c["id"])
    assert r["state"] == "idle" and r["answer"] == "ok" and r["label"] == "Folder reader"
    user = env.payloads(c["id"], "user")[0]
    assert user["text"] == "Read the folder and list its files." and user["by"] == "parent"
    assert env.agent.store.thread(c["id"])["spawn"]["seen"] is False         # finished, not yet looked at


async def test_one_at_a_time_on_a_local_model(env):
    wf = env.agent.workflows
    env.model.queue({"match": "first job", "text": "first done", "delay": 0.6}, {"match": "second job", "text": "second done"})
    p = _parent(env)
    a = await wf.spawn(p["id"], "the first job", "One")
    b = await wf.spawn(p["id"], "the second job", "Two")
    await asyncio.sleep(0.2)
    assert env.agent.running(a["id"]) and env.agent.store.thread(b["id"])["state"] == "queued"
    ra, rb = await _done(env, a["id"]), await _done(env, b["id"])
    assert (ra["answer"], rb["answer"]) == ("first done", "second done")


async def test_remote_models_run_together(env):
    wf = env.agent.workflows
    env.model.groups["main"] = "remote"
    env.model.queue({"match": "first job", "text": "1", "delay": 0.6}, {"match": "second job", "text": "2", "delay": 0.6})
    p = _parent(env)
    a, b = await wf.spawn(p["id"], "the first job", "One"), await wf.spawn(p["id"], "the second job", "Two")
    await asyncio.sleep(0.2)
    assert env.agent.running(a["id"]) and env.agent.running(b["id"])
    await _done(env, a["id"])
    await _done(env, b["id"])


async def test_the_limits(env):
    wf = env.agent.workflows
    p = _parent(env)
    c = await wf.spawn(p["id"], "look", "Child")
    with pytest.raises(WorkflowError) as e:                              # max_depth 1
        await wf.spawn(c["id"], "look deeper", "Grandchild")
    assert e.value.code == "workflow_limit"
    with pytest.raises(WorkflowError) as e:
        await wf.spawn(p["id"], "  ", "Empty")
    assert e.value.code == "invalid_arguments"
    wf.limits.fixed = {"max_children": 2}
    await wf.spawn(p["id"], "look again", "Second")
    with pytest.raises(WorkflowError) as e:
        await wf.spawn(p["id"], "a third", "Third")
    assert e.value.code == "workflow_limit" and "already started 2" in e.value.detail
    assert (await wf.spawn(p["id"], "next turn's", "Next", turn=99))["settings"]["spawn"]["turn"] == 99
    wf.limits.fixed = {"max_children": 8}
    env.model.queue({"match": "change it", "text": "changed", "delay": 0.8})
    w = await wf.spawn(p["id"], "change it", "Writer", write=True)
    with pytest.raises(WorkflowError) as e:                               # one writer at a time
        await wf.spawn(p["id"], "change more", "Writer 2", write=True)
    assert "only one may" in e.value.detail
    await _done(env, w["id"])
    await wf.spawn(p["id"], "change more", "Writer 2", write=True)       # the first one finished
    wf.limits.fixed = {"enabled": False}
    with pytest.raises(WorkflowError) as e:
        await wf.spawn(p["id"], "anything", "Off")
    assert e.value.code == "workflows_off"


async def test_limits_from_the_hub(env):
    env.hub.settings_extra = {"workflows": {"max_children": 1, "unknown": 5}}
    wf = env.agent.workflows
    wf.limits.forget()
    assert (await wf.limits.get())["max_children"] == 1 and "unknown" not in await wf.limits.get()
    p = _parent(env)
    await wf.spawn(p["id"], "one", "One")
    with pytest.raises(WorkflowError):
        await wf.spawn(p["id"], "two", "Two")


async def test_the_answer_is_capped_and_refusals_listed(env):
    wf = env.agent.workflows
    env.model.queue({"match": "big job", "tool_calls": [{"name": "fake_wipe", "arguments": {"id": "x"}}]},
                    {"match": "fake_wipe", "text": " ".join(f"line{i}" for i in range(ANSWER_CHARS // 5))})
    p = _parent(env, unattended=True)                                     # no one to ask: the wipe is refused
    c = await wf.spawn(p["id"], "the big job", "Big")
    r = await _done(env, c["id"])
    assert r["answer"].endswith(f"open the chat #/chat/{c['id']} for the rest)") and r["refused"] == ["fake_wipe"]
    assert len(r["answer"]) < ANSWER_CHARS + 100


async def test_stopping_the_parent_stops_its_sub_agents(env):
    wf = env.agent.workflows
    env.model.queue({"match": "slow job", "text": "late", "delay": 5})
    p = _parent(env)
    a = await wf.spawn(p["id"], "the slow job", "Slow")
    b = await wf.spawn(p["id"], "the queued job", "Queued")
    await asyncio.sleep(0.2)
    assert env.agent.running(a["id"]) and env.agent.store.thread(b["id"])["state"] == "queued"
    await env.agent.cancel(p["id"])
    assert not env.agent.running(a["id"])
    assert env.agent.store.thread(a["id"])["state"] == "idle" and env.agent.store.thread(b["id"])["state"] == "cancelled"
    assert wf.finished(a["id"]) and wf.finished(b["id"])
    assert "stopped with the chat that started it" in [n["text"] for n in env.payloads(b["id"], "note")]
    assert not env.types(b["id"]).count("assistant")


async def test_the_budget_stops_a_turn_s_sub_agents(env):
    wf = env.agent.workflows
    env.model.queue({"match": "render", "tool_calls": [{"name": "fake_render", "arguments": {"prompt": "x", "seconds": 5}}],
                     "usage": {"prompt_tokens": 900, "completion_tokens": 200}})
    p = _parent(env, mode="bypass")
    env.agent.store.update_thread(p["id"], mode="bypass")
    c = await wf.spawn(p["id"], "render a clip", "Renderer", write=True)       # generating isn't a read
    for _ in range(100):
        if env.events(c["id"], "call"):
            break
        await asyncio.sleep(0.05)
    wf.limits.fixed = {"workflow_tokens": 1000}
    await wf.budgets()
    r = await _done(env, c["id"])
    assert r["state"] == "idle" and any("token budget" in n["text"] for n in env.payloads(c["id"], "note"))
    with pytest.raises(WorkflowError) as e:
        await wf.spawn(p["id"], "one more", "More")
    assert e.value.code == "workflow_budget"


async def test_a_sub_agent_s_calls_carry_its_workflow(env):
    wf = env.agent.workflows
    env.model.queue({"match": "say a", "tool_calls": [{"name": "tts_speak", "arguments": {"text": "a", "name": "x"}}]},
                    {"match": "only reads", "text": "Couldn't."},
                    {"match": "say b", "tool_calls": [{"name": "tts_speak", "arguments": {"text": "b", "name": "x"}}]})
    p = _parent(env)
    env.agent.store.update_thread(p["id"], mode="bypass")
    p = env.agent.store.thread(p["id"])
    r = await _done(env, (await wf.spawn(p["id"], "say a", "Reader"))["id"])
    o = next(a["origin"] for a in env.hub.attempts if a["arguments"].get("text") == "a")
    assert (o["root"], o["parent"], o["read_only"]) == (p["id"], p["id"], True)
    assert r["refused"] == ["tts_speak"] and not [c for c in env.hub.calls if c["name"] == "tts_speak"]
    w = await wf.spawn(p["id"], "say b", "Writer", write=True)
    await _done(env, w["id"])
    o = next(a["origin"] for a in env.hub.attempts if a["arguments"].get("text") == "b")
    assert o["root"] == p["id"] and "read_only" not in o
    assert [c["arguments"]["text"] for c in env.hub.calls if c["name"] == "tts_speak"] == ["b"]


async def test_queued_too_long_is_dropped(env):
    wf = env.agent.workflows
    env.model.queue({"match": "slow job", "text": "late", "delay": 1})
    p = _parent(env)
    await wf.spawn(p["id"], "the slow job", "Slow")
    b = await wf.spawn(p["id"], "the queued job", "Queued")
    wf.limits.fixed = {"queue_wait_s": 0}
    await wf.drain()
    assert env.agent.store.thread(b["id"])["state"] == "error"
    assert (await _done(env, b["id"]))["error"]["code"] == "queue_timeout"
