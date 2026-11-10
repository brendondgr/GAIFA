"""calendar 2.3: alerts fire once at their time, post a toast and the unread count, snooze and come back, done
completes a to-do, missed ones fire late (over 24 h: listed only), and a hub that's down is retried."""

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

NY = ZoneInfo("America/New_York")


def T(*a):
    return datetime(*a, tzinfo=NY).timestamp()


class Hub:
    def __init__(self):
        self.got, self.up = [], True

    async def __call__(self, body):
        if not self.up:
            return False
        self.got.append(body)
        return True

    def toasts(self):
        return [b for b in self.got if b.get("title")]

    def unread(self):
        return [b["unread"] for b in self.got if "unread" in b][-1]


@pytest.fixture
def hub(cal):
    h = Hub()
    cal.alerts.poster = h
    return h


def run(coro):
    return asyncio.run(coro)


def add(client, **kw):
    r = client.post("/v1/items", json=kw)
    assert r.status_code == 200, r.text
    return r.json()["item"]


def test_event_alert_once_with_snooze(client, cal, hub):
    add(client, title="Lunch", start="2026-11-13T13:00", end="2026-11-13T14:00")      # default: 10 min before
    a = cal.alerts
    run(a.tick(T(2026, 11, 13, 12, 49)))
    assert hub.toasts() == []
    run(a.tick(T(2026, 11, 13, 12, 50, 10)))
    t = hub.toasts()
    assert len(t) == 1 and t[0]["title"] == "Lunch" and t[0]["body"] == "in 10 min · 13:00–14:00"
    assert [x["label"] for x in t[0]["actions"]] == ["Snooze 10 min"] and t[0]["route"].startswith("#/calendar?item=c_")
    assert hub.unread() == 1
    run(a.tick(T(2026, 11, 13, 12, 51)))
    assert len(hub.toasts()) == 1                                                       # once
    fid = a.list("unread")[0]["id"]
    r = client.post(f"/v1/alerts/{fid}/snooze", params={"minutes": 10})
    assert r.json()["state"] == "snoozed"
    run(a.tick(T(2026, 11, 13, 12, 50, 10) + 601))
    assert len(hub.toasts()) == 2 and hub.toasts()[1]["key"] == fid


def test_todo_alert_and_done_completes_it(client, cal, hub):
    t = add(client, kind="todo", title="Call the bank", due="2026-11-10T10:00")
    run(cal.alerts.tick(T(2026, 11, 10, 9, 59, 50)))
    run(cal.alerts.tick(T(2026, 11, 10, 10, 0, 5)))
    toast = hub.toasts()[0]
    assert toast["body"] == "due 10:00" and [x["label"] for x in toast["actions"]] == ["Snooze 10 min", "Done"]
    fid = cal.alerts.list("unread")[0]["id"]
    client.post(f"/v1/alerts/{fid}/done")
    assert cal.store.get(t["id"])["done_at"] and hub.unread() == 0


def test_all_day_alerts(client, cal, hub):
    add(client, title="Trip", start="2026-11-20", all_day=True, alerts=[60])
    add(client, kind="todo", title="Rent", due="2026-11-20")                          # 0: that day at 09:00
    run(cal.alerts.tick(T(2026, 11, 19, 8, 59)))
    run(cal.alerts.tick(T(2026, 11, 19, 9, 0, 1)))
    assert [x["title"] for x in hub.toasts()] == ["Trip"]
    run(cal.alerts.tick(T(2026, 11, 20, 8, 59)))
    run(cal.alerts.tick(T(2026, 11, 20, 9, 0, 1)))
    assert [x["title"] for x in hub.toasts()] == ["Trip", "Rent"] and hub.toasts()[1]["body"] == "due today"


def test_repeating_todo_done_from_alert(client, cal, hub):
    t = add(client, kind="todo", title="Trash", due="2026-11-03T19:00", repeat="every Tuesday")
    run(cal.alerts.tick(T(2026, 11, 3, 18, 59)))
    run(cal.alerts.tick(T(2026, 11, 3, 19, 0, 30)))
    fid = cal.alerts.list("unread")[0]["id"]
    client.post(f"/v1/alerts/{fid}/done")
    occ = client.get("/v1/range", params={"from": "2026-11-01", "to": "2026-11-12"}).json()["occurrences"]
    assert [(o["occurrence"], o["done"]) for o in occ] == [("2026-11-03T19:00", True), ("2026-11-10T19:00", False)]
    assert t["id"] == occ[0]["item_id"]


def test_missed_late_and_old(client, cal, hub):
    add(client, title="Old", start="2026-11-10T09:00")
    add(client, title="Recent", start="2026-11-11T09:00")
    cal.alerts._set_checked(T(2026, 11, 9, 0, 0))                    # the mod was down since Nov 9
    run(cal.alerts.tick(T(2026, 11, 11, 12, 0)))
    rows = {r["title"]: r for r in cal.alerts.list()}
    assert rows["Old"]["late"] and rows["Old"]["posted"] and rows["Recent"]["late"]
    assert [x["title"] for x in hub.toasts()] == ["Recent"] and "missed" in hub.toasts()[0]["body"]
    assert hub.unread() == 2


def test_hub_down_then_back(client, cal, hub):
    add(client, title="Meet", start="2026-11-13T13:00")
    hub.up = False
    run(cal.alerts.tick(T(2026, 11, 13, 12, 49)))
    run(cal.alerts.tick(T(2026, 11, 13, 12, 50, 10)))
    assert hub.got == [] and len(cal.alerts.list("unread")) == 1
    hub.up = True
    run(cal.alerts.tick(T(2026, 11, 13, 12, 50, 30)))
    assert [x["title"] for x in hub.toasts()] == ["Meet"]


def test_routes_and_seen_all(client, cal, hub):
    add(client, title="A", start="2026-11-13T13:00")
    add(client, title="B", start="2026-11-13T13:00", calendar=None)
    run(cal.alerts.tick(T(2026, 11, 13, 12, 49)))
    run(cal.alerts.tick(T(2026, 11, 13, 12, 50, 10)))
    r = client.get("/v1/alerts", params={"state": "unread"}).json()
    assert r["unread"] == 2 and len(r["alerts"]) == 2
    assert client.post("/v1/alerts/seen-all").json() == {"seen": 2}
    assert hub.unread() == 0 and client.get("/v1/status").json()["stats"][2]["value"] == 0
    assert client.post("/v1/alerts/f_nope/seen").status_code == 404
