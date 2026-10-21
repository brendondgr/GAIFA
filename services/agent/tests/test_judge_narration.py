"""The Auto judge's `context = "full"` (plan 30.4): the agent sends its own text since the user's last message as
`origin.narration` ([{ts, text}]), in Auto only; the hub reads it with the calls it recorded and never stores it."""

from __future__ import annotations

from agent import context as ctx


def test_narration_is_this_turns_text_only():
    evs = [{"seq": 1, "ts": 1.0, "type": "user", "payload": {"text": "first"}},
           {"seq": 2, "ts": 2.0, "type": "assistant", "payload": {"text": "old turn"}},
           {"seq": 3, "ts": 3.0, "type": "user", "payload": {"text": "second"}},
           {"seq": 4, "ts": 4.0, "type": "assistant", "payload": {"text": "  "}},
           {"seq": 5, "ts": 5.0, "type": "tool_call", "payload": {"name": "x"}},
           {"seq": 6, "ts": 6.0, "type": "assistant", "payload": {"text": "I'll read the bill " + "z" * 3000}}]
    out = ctx.narration(evs)
    assert [o["ts"] for o in out] == [6.0] and len(out[0]["text"]) == 2000
    assert ctx.narration(evs[:3]) == []


async def test_auto_sends_the_agents_text_with_the_users_words(env):
    auto = await env.thread(mode="auto")
    env.model.queue({"text": "Reading it first.", "tool_calls": [{"name": "fake_make_image", "arguments": {"prompt": "x"}}]},
                    {"text": "made"})
    await env.send(auto, "make x")
    origin = env.hub.attempts[-1]["origin"]
    assert [n["text"] for n in origin["narration"]] == ["Reading it first."] and origin["said"] == ["make x"]
    manual = await env.thread(mode="manual")
    env.model.queue({"text": "ok", "tool_calls": [{"name": "fake_make_image", "arguments": {"prompt": "w"}}]}, {"text": "ok"})
    await env.send(manual, "make w")
    assert "narration" not in (env.hub.attempts[-1]["origin"] or {})
