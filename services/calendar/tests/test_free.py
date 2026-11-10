from datetime import date, datetime
from zoneinfo import ZoneInfo

import free as F

NY = ZoneInfo("America/New_York")
MON = datetime(2026, 11, 9, 7, 0, tzinfo=NY)


def add(client, **kw):
    r = client.post("/v1/items", json=kw)
    assert r.status_code == 200, r.text
    return r.json()["item"]


def slots(cal, frm=(2026, 11, 9), to=(2026, 11, 10), **kw):
    return [(s["start"][11:], s["end"][11:]) for s in F.free(cal.items, cal.settings.get(), datetime(*frm, tzinfo=NY),
                                                              datetime(*to, tzinfo=NY), now=MON, **kw)]


def test_overlaps_merge_and_working_hours(client, cal):
    add(client, title="A", start="2026-11-09T10:00", end="2026-11-09T11:00")
    add(client, title="B", start="2026-11-09T10:30", end="2026-11-09T12:00")
    add(client, title="C", start="2026-11-09T15:00", end="2026-11-09T15:20")
    assert slots(cal) == [("09:00", "10:00"), ("12:00", "15:00"), ("15:20", "17:00")]


def test_all_day_free_and_focus(client, cal):
    add(client, title="Holiday", start="2026-11-09", all_day=True)
    add(client, title="Lunch?", start="2026-11-09T12:00", end="2026-11-09T13:00", busy="free")
    add(client, title="Deep work", start="2026-11-09T09:00", end="2026-11-09T11:00", busy="focus")
    assert slots(cal) == [("11:00", "17:00")]
    assert slots(cal, include_focus=True) == [("09:00", "17:00")]


def test_min_and_any_and_weekends(client, cal):
    add(client, title="A", start="2026-11-09T09:00", end="2026-11-09T16:40")
    assert slots(cal) == []                                       # 20 minutes < 30
    assert slots(cal, min_minutes=15) == [("16:40", "17:00")]
    assert slots(cal, frm=(2026, 11, 14), to=(2026, 11, 15)) == []   # Saturday: no working hours
    assert slots(cal, frm=(2026, 11, 14), to=(2026, 11, 15), within="any")[0] == ("00:00", "00:00")


def test_working_hours_by_weekday(client, cal):
    client.patch("/v1/settings", json={"work_hours": [["08:00", "12:00"]] + [["09:00", "17:00"]] * 4 + [None, None]})
    assert slots(cal) == [("08:00", "12:00")]


def test_route(client):
    r = client.get("/v1/free", params={"from": "2030-01-07", "to": "2030-01-08", "min": 60}).json()
    assert r["slots"][0]["start"] == "2030-01-07T09:00" and r["minutes"] == 480


def test_plan_day(client, cal):
    add(client, title="Busy", start="2026-11-09T09:00", end="2026-11-09T12:00")
    add(client, kind="todo", title="Low", due="2026-11-09", priority=1, estimate_min=60)
    add(client, kind="todo", title="Overdue", due="2026-11-05", estimate_min=90)
    add(client, kind="todo", title="High", due="2026-11-09", priority=3)
    add(client, kind="todo", title="Huge", due="2026-11-09", estimate_min=400)
    add(client, kind="todo", title="Later", due="2026-11-20")
    p = F.plan_day(cal.items, cal.settings.get(), date(2026, 11, 9), now=MON)
    assert [(b["title"], b["start"][11:], b["end"][11:]) for b in p["items"]] == [
        ("Overdue", "12:00", "13:30"), ("High", "13:40", "14:10"), ("Low", "14:20", "15:20")]
    assert [x["title"] for x in p["left"]] == ["Huge"]


def test_plan_route_makes_a_proposal(client):
    add(client, kind="todo", title="Write", due="2030-01-07", estimate_min=45)
    p = client.post("/v1/plan", json={"date": "2030-01-07"}).json()
    assert p["kind"] == "plan" and p["items"][0]["view"]["start"] == "2030-01-07T09:00"
    r = client.post(f"/v1/proposals/{p['id']}/accept", json={}).json()
    assert r["added"] == 1
