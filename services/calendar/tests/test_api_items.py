from conftest import AGENT


def add(client, **kw):
    r = client.post("/v1/items", json=kw)
    assert r.status_code == 200, r.text
    return r.json()


def rng(client, frm="2026-11-01", to="2026-12-01", **q):
    return client.get("/v1/range", params={"from": frm, "to": to, **q}).json()["occurrences"]


def test_create_with_words_and_undo(client):
    r = add(client, title="Lunch w/ Sam", when="2026-11-13 1pm for 90 min")
    it = r["item"]
    assert (it["start"], it["end"], it["calendar"]) == ("2026-11-13T13:00", "2026-11-13T14:30", "Personal")
    assert it["alerts"] == [{"before_min": 10}] and r["undo"].startswith("/api/s/calendar/v1/undo/")
    assert [o["title"] for o in rng(client)] == ["Lunch w/ Sam"]
    client.post(r["undo"].removeprefix("/api/s/calendar"))
    assert rng(client) == []


def test_bad_when_and_missing_fields(client):
    r = client.post("/v1/items", json={"title": "x", "when": "sometime soonish"})
    assert r.status_code == 422 and r.json()["code"] == "unreadable_when"
    assert client.post("/v1/items", json={"title": "x"}).json()["code"] == "no_start"
    assert client.post("/v1/items", json={"when": "tomorrow"}).json()["code"] == "invalid_title"
    bad = client.post("/v1/items", json={"title": "x", "start": "2026-11-13T13:00", "end": "2026-11-13T12:00"})
    assert bad.json()["code"] == "end_before_start"
    assert client.post("/v1/items", json={"title": "x", "when": "fri", "calendar": "Nope"}).json()["code"] == "unknown_calendar"


def test_todo_and_done(client):
    t = add(client, kind="todo", title="Pay rent", due="2026-11-30")["item"]
    assert t["all_day"] and t["alerts"] == [{"before_min": 0}]
    r = client.post(f"/v1/items/{t['id']}/done").json()
    assert r["done"] and r["item"]["done_at"]
    assert client.post(f"/v1/items/{t['id']}/done", params={"undone": True}).json()["item"]["done_at"] is None


def test_repeating_todo_done_per_occurrence(client):
    t = add(client, kind="todo", title="Trash out", due="2026-11-03T19:00", repeat="every Tuesday")["item"]
    assert t["repeat"] == "Weekly on Tue"
    client.post(f"/v1/items/{t['id']}/done", params={"occurrence": "2026-11-03T19:00"})
    occ = rng(client, kinds="todo")
    assert [(o["due"], o["done"]) for o in occ[:2]] == [("2026-11-03T19:00", True), ("2026-11-10T19:00", False)]


def test_scopes_this_following_all(client):
    it = add(client, title="Standup", start="2026-11-02T09:00", end="2026-11-02T09:15", rrule="FREQ=DAILY;COUNT=10")["item"]
    iid = it["id"]
    client.patch(f"/v1/items/{iid}", params={"occurrence": "2026-11-03T09:00", "scope": "this"}, json={"title": "Standup (late)", "start": "2026-11-03T10:00"})
    occ = rng(client, to="2026-11-05")
    assert [(o["start"], o["title"]) for o in occ] == [("2026-11-02T09:00", "Standup"), ("2026-11-03T10:00", "Standup (late)"),
                                                      ("2026-11-04T09:00", "Standup")]
    r = client.patch(f"/v1/items/{iid}", params={"occurrence": "2026-11-06T09:00", "scope": "following"}, json={"start": "2026-11-06T08:30"}).json()
    new = r["item"]
    assert new["id"] != iid and new["rrule"] == "FREQ=DAILY;COUNT=6" and new["start"] == "2026-11-06T08:30"
    occ = rng(client)
    assert len(occ) == 10 and [o["start"][11:] for o in occ][3:5] == ["09:00", "08:30"]
    client.post(r["undo"].removeprefix("/api/s/calendar"))
    assert [o["start"][11:] for o in rng(client)][4] == "09:00"
    client.patch(f"/v1/items/{iid}", json={"start": "2026-11-02T09:30"})           # all: the series moves, the override follows
    occ = rng(client, to="2026-11-05")
    assert [(o["start"], o["title"]) for o in occ] == [("2026-11-02T09:30", "Standup"), ("2026-11-03T10:00", "Standup (late)"),
                                                      ("2026-11-04T09:30", "Standup")]


def test_delete_scopes_trash_restore(client):
    it = add(client, title="Gym", start="2026-11-02T18:00", rrule="FREQ=DAILY;COUNT=5")["item"]
    iid = it["id"]
    client.delete(f"/v1/items/{iid}", params={"occurrence": "2026-11-03T18:00", "scope": "this"})
    client.delete(f"/v1/items/{iid}", params={"occurrence": "2026-11-05T18:00", "scope": "following"})
    assert [o["occurrence"][8:10] for o in rng(client)] == ["02", "04"]
    r = client.delete(f"/v1/items/{iid}").json()
    assert r["note"].startswith("moved to the trash") and rng(client) == []
    assert [i["id"] for i in client.get("/v1/trash").json()["items"]] == [iid]
    client.post(f"/v1/trash/{iid}/restore")
    assert len(rng(client)) == 2
    assert client.delete(f"/v1/items/{iid}", params={"occurrence": "2026-11-09T18:00", "scope": "this"}).json()["code"] == "no_occurrence"


def test_agent_source_and_ownership(client, cal):
    a = client.post("/v1/items", json={"title": "Test", "when": "2026-11-20 10am"}, headers=AGENT).json()["item"]
    assert a["source"] == {"kind": "agent", "thread": "t_abc", "task": None} and a["by_agent"]
    client.patch(f"/v1/items/{a['id']}", json={"title": "Test 2"}, headers=AGENT)
    assert cal.store.get(a["id"])["touched_by"] == "agent"
    client.patch(f"/v1/items/{a['id']}", json={"title": "Mine now"})
    assert cal.store.get(a["id"])["touched_by"] == "you"


def test_range_across_dst_and_bad_range(client):
    add(client, title="Daily", start="2026-10-31T09:00", rrule="FREQ=DAILY;COUNT=3")
    occ = rng(client, frm="2026-10-31", to="2026-11-03")
    assert [o["start"] for o in occ] == ["2026-10-31T09:00", "2026-11-01T09:00", "2026-11-02T09:00"]
    assert client.get("/v1/range", params={"from": "2026-11-02", "to": "2026-11-01"}).json()["code"] == "bad_range"


def test_calendars_routes(client):
    w = client.post("/v1/calendars", json={"name": "Work"}).json()
    it = add(client, title="Review", when="2026-11-12 2pm", calendar="work")["item"]
    assert it["calendar_id"] == w["id"]
    client.patch(f"/v1/calendars/{w['id']}", json={"hidden": True})
    assert rng(client) == []
    assert client.delete(f"/v1/calendars/{w['id']}").json()["code"] == "calendar_has_items"
    client.delete(f"/v1/calendars/{w['id']}", params={"items": "trash"})
    assert len(client.get("/v1/calendars").json()) == 1


def test_search_next_parse_settings(client):
    it = add(client, title="Dentist", when="2026-11-14 3pm", location="Main St")["item"]
    assert client.get("/v1/search", params={"q": "main"}).json()["items"][0]["id"] == it["id"]
    nxt = client.get(f"/v1/items/{it['id']}/next", params={"after": "2026-11-01"}).json()
    assert nxt["next"]["occurrence"] == "2026-11-14T15:00"
    p = client.get("/v1/parse", params={"text": "standup every weekday at 9"}).json()
    assert p["repeat"] == "Every weekday" and p["title"] == "standup"
    assert client.patch("/v1/settings", json={"date_order": "dmy"}).json()["date_order"] == "dmy"
    assert client.patch("/v1/settings", json={"week_start": 3}).json()["code"] == "invalid_setting"
