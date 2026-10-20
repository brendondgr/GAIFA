"""22.3: a recorded chat becomes a replay task; the base and a candidate harness score differently on
the pre-chosen check (the share of fields the user had changed that the candidate picks itself)."""

from __future__ import annotations

import httpx

from agent.learn import replay

EVENTS = [
    {"type": "user", "payload": {"text": "make a landscape of hills"}},
    {"type": "approval", "payload": {"id": "c1", "approval_id": "ap_1", "tool": "fake_make_image", "arguments": {"prompt": "hills", "aspect": "1:1"}}},
    {"type": "decision", "payload": {"id": "c1", "approve": True, "arguments": {"prompt": "hills", "aspect": "16:9"}}},
    {"type": "tool_result", "payload": {"id": "c1", "status": "done"}},
]


def test_a_record_from_events():
    rec = replay.record(EVENTS, "t_x")
    assert rec.turns == ["make a landscape of hills"] and rec.cards[0]["edited"] == ["aspect"] and rec.edited == 1


async def test_base_and_candidate_score_differently(env):
    rec = replay.record(EVENTS, "t_x")
    tr = httpx.ASGITransport(app=env.app)
    env.model.queue({"tool_calls": [{"name": "load_tools", "arguments": {"names": ["fake_make_image"]}}]},
                    {"tool_calls": [{"name": "fake_make_image", "arguments": {"prompt": "hills", "aspect": "1:1"}}]}, {"text": "done"})
    base = await replay.replay(rec, 0, "http://agent", "main", transport=tr)
    env.model.queue({"tool_calls": [{"name": "load_tools", "arguments": {"names": ["fake_make_image"]}}]},
                    {"tool_calls": [{"name": "fake_make_image", "arguments": {"prompt": "hills", "aspect": "16:9"}}]}, {"text": "done"})
    cand = await replay.replay(rec, 0, "http://agent", "main", transport=tr)
    assert base["pre_chosen"] == 0.0 and cand["pre_chosen"] == 1.0 and base["ran"] and cand["ran"]
    # the replay ran with the user's recorded card: what ran is 16:9 both times
    assert [c["arguments"] for c in env.hub.calls][-1]["aspect"] == "16:9"
