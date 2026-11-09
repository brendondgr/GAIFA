from conftest import AGENT


def test_propose_readable_and_not_then_accept_some_and_undo(client):
    p = client.post("/v1/proposals", headers=AGENT, json={"source": {"kind": "document", "title": "Syllabus"}, "items": [
        {"title": "Quiz 1", "when": "2026-11-12 10am for 30 min"},
        {"title": "Essay", "kind": "todo", "when": "nov 20"},
        {"title": "Field trip", "when": "sometime in spring"}]}).json()
    assert p["count"] == 2 and p["items"][2]["problem"]["code"] == "unreadable_when"
    assert p["items"][0]["view"]["start"] == "2026-11-12T10:00" and p["items"][1]["view"]["due"] == "2026-11-20"
    occ = client.get("/v1/range", params={"from": "2026-11-01", "to": "2026-12-01"}).json()["occurrences"]
    assert occ == []                                                     # proposing adds nothing
    w = client.post("/v1/calendars", json={"name": "School"}).json()
    r = client.post(f"/v1/proposals/{p['id']}/accept", json={"ids": ["1", "3"], "calendar": "School", "project_id": "p_x"}).json()
    assert r["added"] == 1
    occ = client.get("/v1/range", params={"from": "2026-11-01", "to": "2026-12-01"}).json()["occurrences"]
    assert [(o["title"], o["calendar_id"], o["project_id"]) for o in occ] == [("Quiz 1", w["id"], "p_x")]
    assert client.post(f"/v1/proposals/{p['id']}/accept", json={}).json()["code"] == "already_accepted"
    client.post(r["undo"].removeprefix("/api/s/calendar"))
    assert client.get("/v1/range", params={"from": "2026-11-01", "to": "2026-12-01"}).json()["occurrences"] == []


def test_accepted_items_are_yours(client, cal):
    p = client.post("/v1/proposals", headers=AGENT, json={"items": [{"title": "X", "when": "2026-11-12 10am"}]}).json()
    r = client.post(f"/v1/proposals/{p['id']}/accept", json={}).json()
    it = cal.store.get(r["items"][0])
    assert it["touched_by"] == "you" and it["source"]["proposal"] == p["id"]


def test_nothing_chosen(client):
    p = client.post("/v1/proposals", json={"items": [{"title": "X", "when": "nope nope"}]}).json()
    assert client.post(f"/v1/proposals/{p['id']}/accept", json={}).json()["code"] == "nothing_chosen"
