"""14.7: the window from meta and from the setting, the meter, result capping and read_result,
both compaction stages, the thrash guard, and the system prompt order."""

from __future__ import annotations

import json

from agent import context as ctx


async def test_window_from_meta_and_default(env):
    tid = await env.thread()
    await env.send(tid, "hi")
    m = (await env.client.get(f"/v1/threads/{tid}/context")).json()
    assert m["window"] == 8000 and m["model"] == "main"
    env.model.models.pop("main")
    env.agent.llm._models = (0.0, [])
    m = (await env.client.get(f"/v1/threads/{tid}/context")).json()
    assert m["window"] == env.agent.cfg.default_window


async def test_meter_follows_usage_plus_estimate(env):
    env.model.queue({"text": "answer", "usage": {"prompt_tokens": 1000, "completion_tokens": 50}})
    tid = await env.thread()
    await env.send(tid, "question")
    m = (await env.client.get(f"/v1/threads/{tid}/context")).json()
    assert m["used"] == 1050 and m["estimated"] is False
    assert set(m["breakdown"]) == {"instructions", "skills_memory", "tool_index", "outputs", "tools", "messages", "documents", "tool_results"}
    assert abs(sum(m["breakdown"].values()) - 1050) < 60
    env.agent.emit(tid, "user", {"text": "x" * 4000})     # added since the last usage: estimated
    m2 = (await env.client.get(f"/v1/threads/{tid}/context")).json()
    assert 1050 + 900 < m2["used"] < 1050 + 1100


def test_cap_text_and_rebuild_placement():
    text, cut = ctx.cap_text("x" * 20000, tokens=1000)
    assert cut and len(text) < 4200 and "read_result" in text
    events = [
        {"seq": 1, "type": "user", "payload": {"text": "go"}},
        {"seq": 2, "type": "tool_call", "payload": {"id": "a", "name": "t", "arguments": {}, "step": "s1"}},
        {"seq": 3, "type": "tool_call", "payload": {"id": "b", "name": "t", "arguments": {}, "step": "s1"}},
        {"seq": 4, "type": "user", "payload": {"text": "queued"}},
        {"seq": 5, "type": "tool_result", "payload": {"id": "b", "name": "t", "status": "done", "content": "B"}},
        {"seq": 6, "type": "tool_result", "payload": {"id": "a", "name": "t", "status": "done", "content": "A"}},
    ]
    msgs, _ = ctx.rebuild(events)
    assert [m["role"] for m in msgs] == ["user", "assistant", "tool", "tool", "user"]
    assert [m.get("content") for m in msgs[2:4]] == ["A", "B"]        # in call order, right after the call
    # an unanswered call that isn't the pending step gets a stub instead of breaking the API's rules
    msgs, _ = ctx.rebuild(events[:4])
    assert msgs[2]["content"].startswith("[not run")


async def test_long_result_is_capped_and_read_result_pages(env):
    env.model.models["main"]["context_length"] = 12000      # room for one capped result without clearing it
    env.agent.llm._models = (0.0, [])
    env.hub.tools["fake_get"]["risk"] = "read"
    orig = env.hub._execute

    async def big(cid, name, args, mode):
        r = await orig(cid, name, args, mode)
        r["result"] = {"rows": "y" * 30000}
        return r

    env.hub._execute = big
    env.model.queue({"tool_calls": [{"name": "fake_get", "arguments": {"id": "1"}}]}, {"text": "big"})
    tid = await env.thread()
    await env.send(tid, "get big")
    tool_msg = [m for m in env.model.received[-1]["messages"] if m["role"] == "tool"][0]
    assert len(tool_msg["content"]) <= ctx.RESULT_CAP_TOKENS * 4 + 200 and "read_result" in tool_msg["content"]
    seq = env.events(tid, "tool_result")[0]["seq"]
    env.model.queue({"tool_calls": [{"name": "read_result", "arguments": {"seq": seq, "offset": 100, "limit": 50}}]}, {"text": "read"})
    await env.send(tid, "read more")
    page = json.loads(env.payloads(tid, "tool_result")[-1]["content"])
    assert page["offset"] == 100 and len(page["text"]) == 50 and page["total"] > 30000


async def test_compaction_clears_then_summarizes_and_keeps_working(env):
    env.model.models["main"]["context_length"] = 9000
    env.agent.llm._models = (0.0, [])
    orig = env.hub._execute

    async def big(cid, name, args, mode):
        r = await orig(cid, name, args, mode)
        r["result"] = {"rows": "z" * 6000}
        return r

    env.hub._execute = big
    tid = await env.thread()
    for i in range(4):     # four turns, each with a big tool result
        env.model.queue({"tool_calls": [{"name": "hub_list_services", "arguments": {}}]}, {"text": f"turn {i} done"})
        await env.send(tid, f"turn {i} please")
    stages = [p["stage"] for p in env.payloads(tid, "compact")]
    assert "clear" in stages
    env.model.queue({"text": "SUMMARY: the user ran four checks.", "match": "Summarize the conversation"}, {"text": "still here"})
    r = await env.client.post(f"/v1/threads/{tid}/compact")
    assert r.status_code == 200
    summ = [p for p in env.payloads(tid, "compact") if p["stage"] == "summary"]
    assert summ and summ[-1]["summary"].startswith("SUMMARY")
    await env.send(tid, "are you still there?")
    sys_prompt = env.model.received[-1]["messages"][0]["content"]
    assert "## Earlier in this chat (summary)" in sys_prompt and "SUMMARY: the user ran four checks." in sys_prompt
    assert "turn 0 please" not in json.dumps(env.model.received[-1]["messages"][1:])   # summarized away
    assert env.payloads(tid, "assistant")[-1]["text"] == "still here"


async def test_thrash_guard_stops_instead_of_looping(env):
    env.model.models["main"]["context_length"] = 2500
    env.agent.llm._models = (0.0, [])
    tid = await env.thread()
    await env.send(tid, "q " + "w" * 12000)        # one message bigger than the window
    err = env.payloads(tid, "error")[-1]
    assert err["code"] == "context_full"
    assert env.agent.store.thread(tid)["state"] == "error"
    assert len(env.model.received) == 0


async def test_system_prompt_order(env):
    data = env.agent.cfg.data
    data.mkdir(parents=True, exist_ok=True)
    (data / "AGENT.md").write_text("Always answer in French.")
    (data / "memory").mkdir()
    (data / "memory" / "MEMORY.md").write_text("- likes 16:9")
    env.model.queue({"tool_calls": [{"name": "fake_make_image", "arguments": {"prompt": "p"}}]}, {"text": "ok"})
    tid = await env.thread(mode="auto")
    await env.send(tid, "image")
    await env.send(tid, "again")
    s = env.model.received[-1]["messages"][0]["content"]
    order = [s.index(h) for h in ("You are GAIFA's assistant", "## Standing instructions", "## Memory", "## Skills",
                                  "## More tools", "## Environment", "## Outputs in this chat")]
    assert order == sorted(order)
    assert "Always answer in French." in s and "likes 16:9" in s and "- fake/drawing: How to pick image settings" in s
    assert "#1 image via fake_make_image" in s


async def test_thread_window_cap(env):
    tid = await env.thread(settings={"window": 3000})
    await env.send(tid, "hi")
    assert (await env.client.get(f"/v1/threads/{tid}/context")).json()["window"] == 3000
    tid2 = await env.thread(settings={"window": 999999})
    await env.send(tid2, "hi")
    assert (await env.client.get(f"/v1/threads/{tid2}/context")).json()["window"] == 8000   # never above the model's


def test_meter_uses_the_estimate_after_a_compaction():
    evs = [{"seq": 1, "type": "user", "payload": {"text": "x"}},
           {"seq": 2, "type": "usage", "payload": {"prompt_tokens": 5000, "completion_tokens": 10}},
           {"seq": 3, "type": "compact", "payload": {"stage": "clear", "cleared": [1]}}]
    m = ctx.meter(evs, 8000, {"messages": 1200, "instructions": 800})
    assert m["used"] == 2000 and m["estimated"] is True


def test_images_cost_a_fixed_amount_not_their_base64():
    """view_output pictures go to the model as data URLs; their base64 length isn't what they cost
    (two 1024 px pictures counted ~100k "tokens" and ended the chat with context_full)."""
    import base64
    from agent import context as cx

    url = "data:image/jpeg;base64," + base64.b64encode(b"x" * 150_000).decode()
    msg = [{"role": "user", "content": [{"type": "text", "text": "(the image from view_output: cat)"},
                                        {"type": "image_url", "image_url": {"url": url}}]}]
    plain = [{"role": "user", "content": [{"type": "text", "text": "(the image from view_output: cat)"},
                                          {"type": "image_url", "image_url": {"url": ""}}]}]
    assert cx.est(msg) == cx.est(plain) + cx.IMAGE_TOKENS
    assert cx.est(msg + msg) < 2 * (cx.IMAGE_TOKENS + 200)
    assert cx.est({"image": {"url": url, "label": "x"}}) < cx.IMAGE_TOKENS + 50     # a stored tool result's picture too
    assert cx.est("plain text " * 100) == len("plain text " * 100) // cx.CHARS_PER_TOKEN
