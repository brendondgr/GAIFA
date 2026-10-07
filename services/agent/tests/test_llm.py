"""14.3: the model client: streaming, both reasoning fields, leaked tool calls, a malformed-argument
retry, and parallel vs sequential batches."""

from __future__ import annotations

import asyncio
import json
import time

from agent.llm import reparse


def test_reparse_gemma_hermes_and_json():
    known = {"fake_get", "tts_speak"}
    text, calls = reparse('Sure. <|tool_call>call:fake_get{id:<|"|>a b<|"|>,n:3}<tool_call|>', known)
    assert text == "Sure." and calls[0].name == "fake_get" and json.loads(calls[0].arguments) == {"id": "a b", "n": 3}
    text, calls = reparse('<tool_call>{"name": "tts_speak", "arguments": {"text": "hi"}}</tool_call>', known)
    assert calls[0].name == "tts_speak" and json.loads(calls[0].arguments) == {"text": "hi"}
    text, calls = reparse('```json\n{"name": "fake_get", "arguments": {"id": "x"}}\n```', known)
    assert calls and calls[0].name == "fake_get"
    text, calls = reparse('{"name": "unknown_tool", "arguments": {}}', known)
    assert not calls     # plain JSON about something else stays text


async def test_streams_text_and_thinking_deltas(env):
    seen = []
    tid = await env.thread()
    q = env.agent.live.subscribe(tid)
    env.model.queue({"text": "abcdefghijklmnop", "thinking": "hmm let me think", "chunk": 3})
    await env.send(tid, "go")
    while not q.empty():
        ev = q.get_nowait()
        if ev["type"] == "delta":
            seen.append((ev["payload"]["kind"], ev["payload"]["text"]))
    assert "".join(t for k, t in seen if k == "text") == "abcdefghijklmnop"
    assert "".join(t for k, t in seen if k == "thinking") == "hmm let me think"
    assert len([1 for k, _ in seen if k == "text"]) > 3   # really streamed
    assert env.payloads(tid, "thinking")[0]["seconds"] >= 0


async def test_leaked_tool_call_is_run(env):
    env.model.queue({"text": "Let me check. ", "leaked": '<|tool_call>call:hub_list_services{}<tool_call|>'}, {"text": "All fine."})
    tid = await env.thread()
    await env.send(tid, "status?")
    calls = env.payloads(tid, "tool_call")
    assert calls[0]["name"] == "hub_list_services" and calls[0]["leaked"] is True
    assert env.payloads(tid, "assistant")[0]["text"] == "Let me check."
    assert env.payloads(tid, "tool_result")[0]["status"] == "done"


async def test_malformed_arguments_go_back_with_the_schema(env):
    env.model.queue({"tool_calls": [{"name": "fake_get", "arguments": '{"id": "a",,}'}]},
                    {"tool_calls": [{"name": "fake_get", "arguments": {"id": "a"}}]}, {"text": "ok"})
    tid = await env.thread()
    await env.send(tid, "get a")
    r1, r2 = env.payloads(tid, "tool_result")
    assert r1["status"] == "error" and r1["error"]["code"] == "invalid_arguments" and "JSON" in r1["error"]["detail"]
    assert '"id"' in r1["error"]["fix"]     # the schema went back
    assert r2["status"] == "done"
    assert len(env.hub.calls) == 1


async def test_read_batches_run_in_parallel_and_others_in_order(env):
    orig = env.hub._execute

    async def slow(cid, name, args, mode):
        env.hub.timeline.append((name, "start", time.monotonic()))
        await asyncio.sleep(0.4)
        env.hub.timeline.append((name, "end", time.monotonic()))
        return await orig(cid, name, args, mode)

    env.hub.timeline = []
    env.hub._execute = slow
    env.model.queue({"tool_calls": [{"name": "fake_get", "arguments": {"id": "1"}}, {"name": "fake_get", "arguments": {"id": "2"}},
                                    {"name": "hub_list_services", "arguments": {}}]}, {"text": "read them"},
                    {"tool_calls": [{"name": "fake_make_image", "arguments": {"prompt": "a"}},
                                    {"name": "fake_make_image", "arguments": {"prompt": "b"}}]}, {"text": "made them"})
    tid = await env.thread(mode="auto")
    t0 = time.monotonic()
    await env.send(tid, "read three")
    assert time.monotonic() - t0 < 1.2     # three 0.4 s reads overlapped
    env.hub.timeline.clear()
    await env.send(tid, "make two")
    tl = env.hub.timeline
    assert [x[1] for x in tl] == ["start", "end", "start", "end"]   # writes ran one after the other


def test_split_planning_and_think_tags():
    from agent.llm import split_planning

    t, r = split_planning("The user wants a fox. I should call the tool.\n\nHere's your fox (#1). Want me to animate it?")
    assert t.startswith("The user wants") and r.startswith("Here's your fox")
    assert split_planning("The user wants a fox. I should ask what style.") == ("", "The user wants a fox. I should ask what style.")
    assert split_planning("Here's your fox.") == ("", "Here's your fox.")


async def test_think_tags_in_content_become_thinking(env):
    env.model.queue({"text": "<think>The user greets me; reply briefly.</think>Hello! How can I help?"},
                    {"text": "The user asked again. I should be brief.\n\nHi again!"})
    tid = await env.thread()
    await env.send(tid, "hi")
    await env.send(tid, "hi again")
    th = env.payloads(tid, "thinking")
    assert th[0]["text"] == "The user greets me; reply briefly." and th[1]["text"].startswith("The user asked again")
    assert [a["text"] for a in env.payloads(tid, "assistant")] == ["Hello! How can I help?", "Hi again!"]


def test_tag_router_streams_think_as_thinking():
    from agent.llm import TagRouter

    r = TagRouter()
    out = []
    for piece in ["<th", "ink>plan", "ning here</th", "ink>Hello", " there"]:
        out += r.feed(piece)
    assert "".join(t for k, t in out if k == "thinking") == "planning here"
    assert "".join(t for k, t in out if k == "text") == "Hello there"
    r = TagRouter()
    assert r.feed("Hi") == [("text", "Hi")] and r.feed(" you") == [("text", " you")]


async def test_gemma_channel_marker_splits_thinking(env):
    env.model.queue({"text": "The image is done. I should tell the user.<channel|>Here's your fox!"},
                    {"text": "<|channel>thoughtPlanning a reply.<channel|>Hello again."})
    tid = await env.thread()
    await env.send(tid, "a")
    await env.send(tid, "b")
    assert [a["text"] for a in env.payloads(tid, "assistant")] == ["Here's your fox!", "Hello again."]
    assert [t["text"] for t in env.payloads(tid, "thinking")] == ["The image is done. I should tell the user.", "Planning a reply."]


def test_close_json_repairs_truncated_arguments():
    from agent.llm import ToolCall, close_json

    assert close_json('{"name": "comfy/choosing-a-workflow') == {"name": "comfy/choosing-a-workflow"}
    assert close_json('{"items": [{"state": "pending", "text": "a') == {"items": [{"state": "pending", "text": "a"}]}
    assert close_json('{"a": 1,') == {"a": 1}
    assert close_json('{"a": "x"}') is None          # nothing to close
    assert close_json('{"a": ]') is None               # broken, not just cut short
    assert ToolCall("1", "read_skill", '{"name": "gen3d/making-3d').parsed() == ({"name": "gen3d/making-3d"}, None)


async def test_parallel_calls_with_dropped_closers_still_run(env):
    env.model.queue({"tool_calls": [{"name": "read_skill", "arguments": '{"name": "fake/drawing'},
                                    {"name": "update_todos", "arguments": '{"items": [{"text": "draw", "state": "pending"}]}'}]},
                    {"text": "ok"})
    tid = await env.thread()
    await env.send(tid, "go")
    by = {r["name"]: r for r in env.payloads(tid, "tool_result")}
    assert by["read_skill"]["status"] == "done" and by["update_todos"]["status"] == "done"


def test_reparse_gemma_without_the_opening_tag():
    known = {"load_tools"}
    text, calls = reparse('load_tools{group:<|"|>comfy<|"|>}<tool_call|>', known)
    assert calls and calls[0].name == "load_tools" and json.loads(calls[0].arguments) == {"group": "comfy"} and text == ""
    assert reparse('unknown{a:1}<tool_call|>', known)[1] == []


async def test_repeated_identical_calls_are_stopped(env):
    env.model.queue(*[{"tool_calls": [{"name": "hub_list_services", "arguments": {}}]} for _ in range(4)], {"text": "done"})
    tid = await env.thread()
    await env.send(tid, "loop")
    res = env.payloads(tid, "tool_result")
    assert [r["status"] for r in res] == ["done", "done", "error", "error"]
    assert res[2]["error"]["code"] == "repeated_call"
    assert len([c for c in env.hub.calls if c["name"] == "hub_list_services"]) == 2
    # the second refused repeat ends the tool phase: that last model call had tool_choice "none"
    assert env.model.received[-1]["tool_choice"] == "none" and "Tools are off for this reply" in json.dumps(env.model.received[-1]["messages"][-1])
    assert env.payloads(tid, "assistant")[-1]["text"] == "done"


async def test_a_turn_that_keeps_repeating_ends_in_words(env):
    """Even if the model still calls a tool when told not to, the turn ends with a reply, not more calls."""
    env.model.queue(*[{"tool_calls": [{"name": "hub_list_services", "arguments": {}}]} for _ in range(8)])
    tid = await env.thread()
    await env.send(tid, "loop")
    assert len(env.payloads(tid, "tool_call")) == 4
    assert "kept repeating" in env.payloads(tid, "assistant")[-1]["text"]
    assert (await env.client.get(f"/v1/threads/{tid}")).json()["state"] == "idle"


async def test_grammar_constrained_models_get_every_tool(env):
    env.model.models["main"]["source"] = "props"
    env.agent.llm._models = (0.0, [])
    tid = await env.thread()
    await env.send(tid, "hi")
    names = {t["function"]["name"] for t in env.model.received[-1]["tools"]}
    assert {"fake_make_image", "tts_speak", "gen3d_make_3d"} <= names


def test_reparse_python_style_calls():
    """The 26B sometimes writes the call as Python text instead of making it."""
    known = {"comfy_generate_image", "tts_speak"}
    text, calls = reparse("comfy_generate_image(aspect='9:16', prompt='a heron standing in a misty marsh, watercolor painting', "
                          "workflow='zimage-intorealism')", known)
    assert text == "" and calls[0].name == "comfy_generate_image"
    assert json.loads(calls[0].arguments) == {"aspect": "9:16", "prompt": "a heron standing in a misty marsh, watercolor painting",
                                              "workflow": "zimage-intorealism"}
    _, calls = reparse("```python\nprint(default_api.tts_speak(text=\"hi\", speed=1.2))\n```", known)
    assert calls[0].name == "tts_speak" and json.loads(calls[0].arguments) == {"text": "hi", "speed": 1.2}
    # prose, unknown tools, positional or non-literal arguments are left alone
    for t in ["I'll call comfy_generate_image(prompt='x') now.", "rm_rf(path='/')", "comfy_generate_image('x')",
              "comfy_generate_image(prompt=open('/etc/passwd').read())", "Sure (of course)."]:
        assert reparse(t, known)[1] == [], t


async def test_a_python_style_call_runs(env):
    env.model.queue({"text": "fake_get(key='a')"}, {"text": "got it"})
    tid = await env.thread(settings={"pinned": ["fake"]})
    await env.send(tid, "get a")
    call = env.payloads(tid, "tool_call")[0]
    assert call["name"] == "fake_get" and call["arguments"] == {"key": "a"} and call.get("leaked")
