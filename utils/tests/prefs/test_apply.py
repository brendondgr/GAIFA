"""21.3: preferences fill the card: only what the caller left out, where the conditions hold;
card edits carry over in the same chat; edits against a preference count against it; MCP callers
get them too; learning off fills nothing."""

from __future__ import annotations


async def pref(th, **body):
    r = await th.client.post("/api/prefs", json=body)
    assert r.status_code == 200, r.text
    return r.json()


async def test_fills_what_the_caller_left_out(th):
    p = await pref(th, tool="fake_tools_make_image", field="aspect", value="16:9")
    r = await th.call("fake_tools_make_image", {"prompt": "a fox"})
    assert r["arguments"]["aspect"] == "16:9" and r["filled"] == ["aspect"]
    ap = (await th.client.get(f"/api/approvals/{r['approval_id']}")).json()
    assert ap["filled"] == {"aspect": f"pref:{p['id']}"}
    r = await th.call("fake_tools_make_image", {"prompt": "a fox", "aspect": "1:1"})
    assert r["arguments"]["aspect"] == "1:1" and "filled" not in r            # an explicit value wins
    assert (await th.client.get(f"/api/prefs")).json()[0]["last_used_ts"]


async def test_conditions_and_capability_defaults(th):
    await pref(th, tool="fake_tools_shape", field="engine", value="body")       # when: a picture
    r = await th.call("fake_tools_shape", {"prompt": "a fox"})
    assert r["arguments"]["engine"] == "words"                                  # no picture: the capability default
    r = await th.call("fake_tools_shape", {"image": "output:000000000000"})
    assert r["arguments"]["engine"] == "body"                                   # the preference beats the default
    assert r["filled"] == ["engine"]


async def test_card_edits_carry_over_in_the_same_chat_only(th):
    r = await th.call("fake_tools_make_image", {"prompt": "a"}, thread="t_one")
    d = await th.client.post(f"/api/approvals/{r['approval_id']}?wait=10", json={"approve": True, "arguments": {"prompt": "a", "aspect": "16:9"}})
    assert d.status_code == 200
    r = await th.call("fake_tools_make_image", {"prompt": "b"}, thread="t_one")
    assert r["arguments"].get("aspect") == "16:9"
    ap = (await th.client.get(f"/api/approvals/{r['approval_id']}")).json()
    assert ap["filled"] == {"aspect": "carried"}
    r = await th.call("fake_tools_make_image", {"prompt": "c"}, thread="t_two")
    assert "aspect" not in r["arguments"]


async def test_edits_against_an_inferred_preference_retire_it(th):
    p = await pref(th, tool="fake_tools_make_image", field="aspect", value="16:9", source="inferred", state="active")
    for n in range(2):
        r = await th.call("fake_tools_make_image", {"prompt": f"x{n}"})
        await th.client.post(f"/api/approvals/{r['approval_id']}?wait=10", json={"approve": True, "arguments": {"prompt": f"x{n}", "aspect": "1:1"}})
    got = (await th.client.get("/api/prefs?tool=fake_tools_make_image&scope=tool")).json()[0]
    assert got["id"] == p["id"] and got["contradicted"] == 2 and got["state"] == "retired"


async def test_mcp_callers_and_learning_off(th):
    await pref(th, tool="fake_tools_make_image", field="aspect", value="16:9")
    r = await th.call("fake_tools_make_image", {"prompt": "a"}, service="mcp", client="claude-code")
    assert r["arguments"]["aspect"] == "16:9"
    r = await th.call("fake_tools_make_image", {"prompt": "a"}, no_learn=True)
    assert "aspect" not in r["arguments"]                                       # a chat that opted out
    th.hub.config.learning.enabled = False
    try:
        r = await th.call("fake_tools_make_image", {"prompt": "a"})
        assert "aspect" not in r["arguments"]
    finally:
        th.hub.config.learning.enabled = True
