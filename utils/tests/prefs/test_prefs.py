"""21.2: preferences: saved, checked against the tool's schema and choices, one row per preference,
approve and reject, learning off."""

from __future__ import annotations


async def post(th, **body):
    return await th.client.post("/api/prefs", json=body)


async def test_create_list_update_delete(th):
    r = await post(th, tool="fake_tools_make_image", field="aspect", value="16:9", cue="landscapes")
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["scope"] == "tool" and p["source"] == "stated" and p["state"] == "active" and p["when"] == {}
    again = (await post(th, tool="fake_tools_make_image", field="aspect", value="16:9")).json()
    assert again["id"] == p["id"] and again["seen"] == 2                       # the same preference: one row
    assert [x["id"] for x in (await th.client.get("/api/prefs?tool=fake_tools_make_image")).json()] == [p["id"]]
    up = (await th.client.patch(f"/api/prefs/{p['id']}", json={"value": "1:1"})).json()
    assert up["value"] == "1:1"
    assert (await th.client.delete(f"/api/prefs/{p['id']}")).json() == {"id": p["id"], "deleted": True}
    assert (await th.client.get(f"/api/prefs")).json() == []


async def test_a_preference_must_fit_the_tool(th):
    r = await post(th, tool="fake_tools_make_image", field="aspect", value="16:10")
    assert r.status_code == 422 and r.json()["code"] == "invalid_pref" and "16:9" in r.json()["detail"]
    r = await post(th, tool="fake_tools_make_image", field="colour", value="red")
    assert r.status_code == 422 and "no parameter" in r.json()["detail"]
    r = await post(th, tool="nope_tool", field="x", value=1)
    assert r.json()["code"] == "unknown_tool"
    p = (await post(th, tool="fake_tools_shape", field="engine", value="body")).json()
    assert p["when"] == {"image": "present"}                                    # a picture engine: only with a picture
    r = await post(th, tool="fake_tools_shape", field="engine", value="body", when={"image": "absent"})
    assert r.status_code == 422 and "needs `image`" in r.json()["detail"]
    a = (await post(th, value="Reply in short sentences.")).json()
    assert a["scope"] == "agent" and a["tool"] is None


async def test_proposed_then_approved_or_rejected(th):
    p = (await post(th, tool="fake_tools_make_image", field="aspect", value="16:9", source="inferred")).json()
    assert p["state"] == "proposed"
    assert (await th.client.post(f"/api/prefs/{p['id']}/approve")).json()["state"] == "active"
    q = (await post(th, tool="fake_tools_make_image", field="steps", value=20, source="inferred")).json()
    assert (await th.client.post(f"/api/prefs/{q['id']}/reject")).json()["state"] == "rejected"
    assert (await th.client.get("/api/prefs/nope/approve")).status_code in (404, 405)


async def test_free_text_is_never_inferred(th):
    """plan 24.8: a prompt (or any free-text field) can be stated, never inferred."""
    r = await post(th, tool="fake_tools_make_image", field="prompt", value="the quarterly report says…", source="inferred")
    assert r.status_code == 422 and r.json()["code"] == "free_text"
    assert (await post(th, tool="fake_tools_make_image", field="prompt", value="a fox")).status_code == 200   # stated: fine


async def test_learning_off_refuses_writes(th):
    th.hub.config.learning.enabled = False
    try:
        r = await post(th, tool="fake_tools_make_image", field="aspect", value="16:9")
        assert r.status_code == 409 and r.json()["code"] == "learning_off"
    finally:
        th.hub.config.learning.enabled = True
