"""Plan 48.3: a message's @-mentions: kept on the user event, said to the model, and pinned on that turn's calls."""

from __future__ import annotations

from agent import context as ctx

MENTION = {"kind": "voice", "id": "Brendon", "label": "Brendon", "fills": ["tts_speak.name"]}


def test_pins_and_the_line():
    p = {"text": "say hi", "mentions": [MENTION, {"kind": "engine", "id": "trellis2", "label": "TRELLIS.2", "fills": ["gen3d_make_3d.engine"]}]}
    assert ctx.pins(p) == {"tts_speak": {"name": "Brendon"}, "gen3d_make_3d": {"engine": "trellis2"}}
    assert ctx.mentions_line(p).startswith("(Named in this message: voice Brendon (tts_speak.name); engine TRELLIS.2")
    assert ctx.pins({"text": "x"}) == {} and ctx.mentions_line({}) == ""


async def test_a_mention_reaches_the_model_and_the_call(env):
    origins = []
    real = env.agent.hub.call

    async def spy(name, args, origin, mode, wait=20):
        origins.append((name, origin.get("pins")))
        return await real(name, args, origin, mode, wait=wait)

    env.agent.hub.call = spy
    env.model.queue({"tool_calls": [{"name": "tts_speak", "arguments": {"text": "Good morning."}}]}, {"text": "Said."})
    tid = await env.thread(mode="auto")
    await env.send(tid, "Say good morning with @voice:Brendon", mentions=[MENTION])
    user = env.payloads(tid, "user")[-1]
    assert user["mentions"] == [MENTION]
    assert any("Named in this message: voice Brendon" in str(m.get("content")) for m in env.model.received[0]["messages"] if m["role"] == "user")
    assert ("tts_speak", {"tts_speak": {"name": "Brendon"}}) in origins
