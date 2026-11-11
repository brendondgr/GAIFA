"""calendar 2.1: POST /api/notify: a mod's toast (a `notification` event and an activity item) and its badge (a
`badge` event and `badge` in /api/services), checked; an unknown mod and bad actions are refused."""

from __future__ import annotations

import httpx

from utils.tests.settings.test_settings import _hub


def _events(sub, kind):
    out = []
    while not sub.queue.empty():
        ev = sub.queue.get_nowait()
        if ev.get("type") == kind:
            out.append(ev)
    return out


async def test_notification_event_and_activity(rig, serve):
    served = await _hub(rig, serve)
    sub = served.hub.bus.subscribe()
    async with httpx.AsyncClient(base_url=served.url) as c:
        r = await c.post("/api/notify", json={"service": "fake-ok", "title": "Lunch with Sam", "body": "in 10 min · 13:00–14:00",
                                              "route": "#/calendar?item=c_1", "key": "f_1",
                                              "actions": [{"label": "Snooze 10 min", "op": "POST /v1/alerts/f_1/snooze"}]})
        assert r.status_code == 200 and r.json()["id"] and r.json()["badge"] is None
    ev = _events(sub, "notification")
    sub.close()
    assert len(ev) == 1 and ev[0]["title"] == "Lunch with Sam" and ev[0]["actions"][0]["op"] == "POST /v1/alerts/f_1/snooze"
    act = served.hub.activity.recent(1)[0]
    assert act["text"] == "Lunch with Sam: in 10 min · 13:00–14:00" and act["service"] == "fake-ok" and act["route"] == "#/calendar?item=c_1"


async def test_badge_alone(rig, serve):
    served = await _hub(rig, serve)
    sub = served.hub.bus.subscribe()
    n = len(served.hub.activity.recent(500))
    async with httpx.AsyncClient(base_url=served.url) as c:
        r = await c.post("/api/notify", json={"service": "fake-ok", "unread": 3})
        assert r.json() == {"id": None, "badge": 3}
        svc = next(s for s in (await c.get("/api/services")).json() if s["id"] == "fake-ok")
        assert svc["badge"] == 3
        await c.post("/api/notify", json={"service": "fake-ok", "unread": 0})
        svc = next(s for s in (await c.get("/api/services")).json() if s["id"] == "fake-ok")
        assert svc["badge"] is None
    assert [e["unread"] for e in _events(sub, "badge")] == [3, 0] and _events(sub, "notification") == []
    sub.close()
    assert len(served.hub.activity.recent(500)) == n


async def test_refusals(rig, serve):
    served = await _hub(rig, serve)
    async with httpx.AsyncClient(base_url=served.url) as c:
        r = await c.post("/api/notify", json={"service": "nope", "title": "x"})
        assert r.status_code == 422 and r.json()["code"] == "unknown_service"
        for bad in ([{"label": "x", "op": "GET /v1/x"}], [{"label": "x", "op": "POST /v1/x"}] * 5, [{"label": "", "op": "POST /v1/x"}]):
            assert (await c.post("/api/notify", json={"service": "fake-ok", "title": "x", "actions": bad})).status_code == 422
        assert (await c.post("/api/notify", json={"service": "fake-ok", "title": "x", "route": "http://evil"})).status_code == 422
