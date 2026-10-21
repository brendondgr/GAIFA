"""21.4: the agent saves what the user states with hub_set_preference (a card in every mode: the default ask list);
thumbs on outputs are kept in the hub."""

from __future__ import annotations


async def test_set_preference_saves_and_applies(th):
    asked = await th.call("hub_set_preference", {"tool": "fake_tools_make_image", "field": "aspect", "value": "16:9", "cue": "always"}, mode="bypass")
    assert asked["status"] == "needs_approval" and await th.hub.prefs.list(state="active") == []   # the default ask list
    r = (await th.client.post(f"/api/approvals/{asked['approval_id']}?wait=20", json={"approve": True})).json()
    assert r["status"] == "done" and r["result"]["saved"]["value"] == "16:9"
    r = await th.call("fake_tools_make_image", {"prompt": "x"})
    assert r["arguments"]["aspect"] == "16:9"
    bad = await th.call("hub_set_preference", {"tool": "fake_tools_make_image", "field": "aspect", "value": "16:10"})   # refused before a card
    assert bad["status"] == "error" and bad["error"]["code"] == "invalid_pref"
    listed = await th.call("hub_list_preferences", {})
    assert [p["field"] for p in listed["result"]["preferences"]] == ["aspect"]


async def test_output_feedback(th):
    r = await th.call("fake_tools_make_image", {"prompt": "a fox"}, mode="auto")
    oid = r["outputs"][0]["output_id"]
    f = await th.client.post(f"/api/outputs/{oid}/feedback", json={"value": "up", "note": "nice"})
    assert f.status_code == 200 and f.json()["value"] == "up"
    assert (await th.client.post("/api/outputs/nope00000000/feedback", json={"value": "up"})).status_code == 404
    rows = await th.hub.db.fetchall("SELECT value, note FROM output_feedback WHERE output_id = ?", (oid,))
    assert [(r["value"], r["note"]) for r in rows] == [("up", "nice")]


async def test_a_preference_that_cant_be_saved_is_refused_before_a_card(th):
    for args in ({"tool": "fake_tools_make_image", "field": "aspect", "value": "16:10"}, {"tool": "nope", "field": "x", "value": 1},
                 {"value": "   "}):
        r = await th.call("hub_set_preference", args, mode="manual")
        assert r["status"] == "error" and r["error"]["code"] in ("invalid_pref", "unknown_tool"), r
    assert (await th.client.get("/api/approvals")).json() == []                     # no card was made
