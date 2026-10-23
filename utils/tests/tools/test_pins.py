"""48.3: @-mentions pinned on a call: filled when the model left them out, asked when it chose otherwise."""

from __future__ import annotations


async def test_a_mention_fills_a_missing_field(th):
    r = await th.call("fake_tools_make_image", {"prompt": "a fox"}, mode="auto", pins={"fake_tools_make_image": {"aspect": "16:9"}})
    assert r["status"] == "done"
    call = await th.hub.db.fetchone("SELECT arguments, filled FROM tool_calls WHERE id = ?", (r["call_id"],))
    assert '"16:9"' in call["arguments"] and '"mention"' in call["filled"]


async def test_a_model_that_chose_otherwise_gets_a_card(th):
    r = await th.call("fake_tools_make_image", {"prompt": "a fox", "aspect": "1:1"}, mode="auto", pins={"fake_tools_make_image": {"aspect": "16:9"}})
    assert r["status"] == "needs_approval" and r["arguments"]["aspect"] == "16:9"
    assert r["filled_by"]["aspect"] == "mention"


async def test_pins_for_other_tools_or_unknown_fields_do_nothing(th):
    r = await th.call("fake_tools_make_image", {"prompt": "a fox", "aspect": "1:1"}, mode="auto",
                      pins={"tts_speak": {"name": "x"}, "fake_tools_make_image": {"colour": "red"}})
    assert r["status"] == "done"
