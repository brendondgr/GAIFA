"""21.4: the agent saves what the user states with hub_set_preference (allowed without a card);
thumbs on outputs are kept in the hub."""

from __future__ import annotations


async def test_set_preference_saves_and_applies(th):
    r = await th.call("hub_set_preference", {"tool": "fake_tools_make_image", "field": "aspect", "value": "16:9", "cue": "always"})
    assert r["status"] == "done" and r["result"]["saved"]["value"] == "16:9"            # in the default allow list
    r = await th.call("fake_tools_make_image", {"prompt": "x"})
    assert r["arguments"]["aspect"] == "16:9"
    bad = await th.call("hub_set_preference", {"tool": "fake_tools_make_image", "field": "aspect", "value": "16:10"})
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
