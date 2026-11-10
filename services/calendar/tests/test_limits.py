"""calendar 4.1: the preflight: reads and proposals read; writes change; the agent's own item from this chat, which
nobody changed since, an edit; an unknown item refused."""

from conftest import AGENT


def pre(client, tool, args, thread="t_abc"):
    return client.post("/v1/limits", json={"tool": tool, "arguments": args, "origin": {"thread": thread}}).json()


def test_reads(client):
    for t in ("agenda", "search", "when", "free", "propose", "plan_day"):
        assert pre(client, t, {})["action"] == "read"


def test_writes_are_changes_with_a_summary(client):
    p = pre(client, "add", {"title": "Lunch", "when": "2026-11-13 1pm"})
    assert p["action"] == "change" and p["allow_bypass"] and p["preview"]["summary"] == "adds “Lunch” · 2026-11-13 13:00"
    mine = client.post("/v1/items", json={"title": "Dentist", "when": "2026-11-14 3pm"}).json()["item"]
    for t in ("update", "done", "delete"):
        assert pre(client, t, {"iid": mine["id"]})["action"] == "change"
    assert "deletes “Dentist”" in pre(client, "delete", {"iid": mine["id"]})["preview"]["summary"]


def test_its_own_item_in_this_chat(client):
    a = client.post("/v1/items", json={"title": "Test", "when": "2026-11-20 10am"}, headers=AGENT).json()["item"]
    assert pre(client, "delete", {"iid": a["id"]})["action"] == "edit"
    assert pre(client, "update", {"iid": a["id"], "title": "x"})["action"] == "edit"
    assert pre(client, "done", {"iid": a["id"]})["action"] == "change"              # completing isn't in OWN
    assert pre(client, "delete", {"iid": a["id"]}, thread="t_other")["action"] == "change"
    client.patch(f"/v1/items/{a['id']}", json={"title": "Now yours"})              # you changed it
    assert pre(client, "delete", {"iid": a["id"]})["action"] == "change"


def test_unknown_item_refused(client):
    p = pre(client, "update", {"iid": "c_nope"})
    assert p["refuse"]["code"] == "not_found"


def test_agenda_rows(client):
    client.post("/v1/items", json={"title": "Standup", "when": "every weekday at 9:15 for 15 min"})
    client.post("/v1/items", json={"kind": "todo", "title": "Rent"})
    r = client.get("/v1/agenda", params={"day": "2030-01-07", "days": 2}).json()
    assert [(x["title"], x["start"], x.get("repeats")) for x in r["items"]] == [("Standup", "2030-01-07T09:15", True), ("Standup", "2030-01-08T09:15", True)]
    assert r["undated_todos"] == [{"id": r["undated_todos"][0]["id"], "title": "Rent"}]
    assert client.get("/v1/agenda", params={"day": "someday"}).json()["code"] == "bad_day"


def test_mentions(client):
    days = client.get("/v1/mentions/days").json()
    assert [d["value"] for d in days[:2]] == ["today", "tomorrow"] and len(days) == 8
    a = client.post("/v1/items", json={"title": "Dentist", "when": "tomorrow 3pm"}).json()["item"]
    items = client.get("/v1/mentions/items").json()
    assert items[0]["value"] == a["id"] and items[0]["label"].startswith("Dentist · ")


def test_many_adds_from_one_chat_are_a_proposal(client):
    """A fourth different add from one chat within two minutes is refused with use_propose; the same add checked again
    (the hub's re-check on approval) isn't counted; another chat has its own count."""
    adds = [{"title": f"Deadline {i}", "when": f"2026-12-0{i + 1}"} for i in range(5)]
    got = [pre(client, "add", a, thread="t_burst") for a in adds]
    assert [g.get("refuse", {}).get("code") for g in got] == [None, None, None, "use_propose", "use_propose"]
    assert "calendar_propose" in got[3]["refuse"]["fix"]
    assert "refuse" not in pre(client, "add", adds[0], thread="t_burst")        # an approved card's re-check
    assert "refuse" not in pre(client, "add", adds[4], thread="t_other")
    assert pre(client, "propose", {"items": adds}, thread="t_burst")["action"] == "read"


def test_the_window_passes():
    from limits import BURST_S, Burst
    b = Burst()
    assert not any(b.over("t", {"n": i}, now=0) for i in range(3))
    assert b.over("t", {"n": 3}, now=1)
    assert not b.over("t", {"n": 3}, now=BURST_S + 1)                        # the first three are older than the window
