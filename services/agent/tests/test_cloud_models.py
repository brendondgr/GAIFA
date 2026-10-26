"""The agent with cloud models (plan llm-servers 2.1): a provider's hidden reasoning state kept per step and
sent back only to its model, the chat purpose on every call that belongs to a chat, and background summaries
kept off paid providers."""

from __future__ import annotations

from agent.llm import THREAD, _headers, for_model

DETAILS = [{"format": "anthropic", "model": "claude-opus-5-5", "block": {"type": "thinking", "thinking": "t", "signature": "sig"}}]


async def test_details_go_back_with_their_step(env):
    env.model.queue({"thinking": "plan", "tool_calls": [{"name": "hub_list_services", "arguments": {}}], "details": DETAILS},
                    {"text": "Done."})
    tid = await env.thread()
    await env.send(tid, "status?")
    assert env.payloads(tid, "reasoning_details")[0]["details"] == DETAILS
    second = env.model.received[1]["messages"]
    assistant = next(m for m in second if m["role"] == "assistant" and m.get("tool_calls"))
    assert assistant["reasoning_details"] == DETAILS and "details_model" not in assistant


async def test_details_stay_with_their_model(env):
    env.model.queue({"tool_calls": [{"name": "hub_list_services", "arguments": {}}], "details": DETAILS}, {"text": "Done."})
    tid = await env.thread()
    await env.send(tid, "status?")
    env.model.queue({"text": "Again."})
    env.agent.store.update_thread(tid, model="backup")                            # the chat switched models
    await env.send(tid, "and now?")
    last = env.model.received[-1]
    assert last["model"] == "backup"
    assert not any("reasoning_details" in m for m in last["messages"])          # another model never sees them


def test_for_model():
    msgs = [{"role": "assistant", "content": "x", "reasoning_details": DETAILS, "details_model": "claude/x"}]
    assert for_model(msgs, "claude/x") == [{"role": "assistant", "content": "x", "reasoning_details": DETAILS}]
    assert for_model(msgs, "local") == [{"role": "assistant", "content": "x"}]
    assert msgs[0]["details_model"] == "claude/x"                                 # the stored events aren't touched


def test_the_purpose_header_follows_the_thread():
    assert _headers() == {}
    token = THREAD.set("t_1")
    try:
        assert _headers() == {"X-GAIFA-Thread": "t_1", "X-GAIFA-Purpose": "chat"}
    finally:
        THREAD.reset(token)


async def test_chat_turns_and_titles_say_chat(env):
    env.model.queue({"text": "Hello."})
    tid = await env.thread()
    await env.send(tid, "hi there, a long enough first message to title")
    assert env.model.headers and all(h.get("x-gaifa-purpose") == "chat" and h.get("x-gaifa-thread") == tid for h in env.model.headers)


async def test_a_cloud_chats_summary_uses_the_local_model(env):
    env.model.groups["main"] = "cloud"
    env.model.queue({"text": "Hello."})
    tid = await env.thread()
    await env.send(tid, "hi")
    env.agent.cfg.model = "backup"
    env.agent.store.update_thread(tid, model="main")
    env.model.queue({"text": "A short summary.", "match": "summar"})
    await env.agent.summaries.summarize(tid)
    asked = env.model.received[-1]
    assert asked["model"] == "backup"                                             # not the chat's cloud model
    assert "x-gaifa-purpose" not in env.model.headers[-1]


async def test_is_cloud(env):
    env.model.groups["main"] = "cloud"
    assert await env.agent.llm.is_cloud("main") and not await env.agent.llm.is_cloud("backup")
