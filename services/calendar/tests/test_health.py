def test_health_and_status(client):
    assert client.get("/health").json() == {"status": "ok"}
    s = client.get("/v1/status").json()
    assert s["rev"] >= 1 and {x["label"] for x in s["stats"]} >= {"Items", "Calendars", "Unread reminders"}


def test_default_calendar(client):
    cals = client.get("/v1/calendars").json()
    assert [c["name"] for c in cals] == ["Personal"] and cals[0]["is_default"]
