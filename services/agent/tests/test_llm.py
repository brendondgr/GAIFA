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
