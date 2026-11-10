from pathlib import Path

FIX = Path(__file__).parent / "fixtures"


def imp(client, name):
    r = client.post("/v1/import", files={"file": (name, (FIX / name).read_bytes(), "text/calendar")})
    assert r.status_code == 200, r.text
    return r.json()


def rng(client, frm="2026-08-01", to="2027-01-01"):
    return client.get("/v1/range", params={"from": frm, "to": to}).json()["occurrences"]


def test_google_series_override_exdate_alarm(client):
    p = imp(client, "google.ics")
    assert [r["fields"]["title"] for r in p["items"]] == ["Lab meeting", "Call with Ana"]
    assert p["skipped"] == [{"title": "Gone", "why": "cancelled"}]
    client.post(f"/v1/proposals/{p['id']}/accept", json={})
    occ = [(o["start"], o["title"]) for o in rng(client, "2026-11-01", "2026-12-01")]
    assert ("2026-11-04T10:00", "Lab meeting") not in occ                 # EXDATE
    assert ("2026-11-11T14:00", "Lab meeting (moved)") in occ             # RECURRENCE-ID
    assert ("2026-11-13T13:00", "Call with Ana") in occ                   # UTC into New York
    assert occ[-1] == ("2026-11-25T10:00", "Lab meeting") and len([o for o in occ if "Lab" in o[1]]) == 7
    lab = next(o for o in rng(client, "2026-11-01", "2026-11-03"))
    assert lab["alerts"] == [{"before_min": 30}] and lab["location"] == "Room 204"


def test_outlook_zone_transparent_todos(client):
    p = imp(client, "outlook.ics")
    rows = {r["fields"]["title"]: r["fields"] for r in p["items"]}
    assert rows["Standup (London)"]["tz"] == "Europe/London" and rows["Standup (London)"]["busy"] == "free"
    assert rows["Submit report"]["due"] == "2026-11-25" and rows["Submit report"]["priority"] == 3
    assert rows["Old task"]["done_at"]
    client.post(f"/v1/proposals/{p['id']}/accept", json={})
    o = next(o for o in rng(client, "2026-11-16", "2026-11-17") if o["kind"] == "event")
    assert o["start"] == "2026-11-16T04:00"


def test_syllabus_all_day_skipped_and_already_here(client):
    p = imp(client, "syllabus.ics")
    assert [r["fields"]["title"] for r in p["items"]] == ["HW 1 due", "Midterm", "Finals week"]
    assert p["skipped"] == [{"title": "No start", "why": "no start"}]
    fin = p["items"][2]["fields"]
    assert (fin["start"], fin["end"], fin["all_day"]) == ("2026-12-08", "2026-12-11", True)
    client.post(f"/v1/proposals/{p['id']}/accept", json={"ids": ["1", "2"]})
    again = imp(client, "syllabus.ics")
    assert [r["already"] for r in again["items"]] == [True, True, False]
    r = client.post(f"/v1/proposals/{again['id']}/accept", json={}).json()
    assert r["added"] == 1


def test_round_trip(client):
    p = imp(client, "google.ics")
    client.post(f"/v1/proposals/{p['id']}/accept", json={})
    before = [(o["start"], o["end"], o["title"]) for o in rng(client)]
    data = client.get("/v1/export.ics").content
    assert b"RECURRENCE-ID" in data and b"EXDATE" in data
    for i in client.get("/v1/search", params={"q": "a"}).json()["items"]:
        client.delete(f"/v1/items/{i['id']}")
    assert rng(client) == []
    p2 = client.post("/v1/import", json={"ics": data.decode()}).json()
    assert all(not r["already"] for r in p2["items"])
    client.post(f"/v1/proposals/{p2['id']}/accept", json={})
    assert [(o["start"], o["end"], o["title"]) for o in rng(client)] == before
    one = client.get(f"/v1/items/{p2['items'][0]['fields']['source']['ref'] and client.get('/v1/search', params={'q': 'Lab'}).json()['items'][0]['id']}.ics")
    assert one.status_code == 200 and b"BEGIN:VEVENT" in one.content


def test_bad_file(client):
    assert client.post("/v1/import", json={"ics": "hello"}).json()["code"] == "bad_ics"
    assert client.post("/v1/import", json={}).json()["code"] == "no_file"
