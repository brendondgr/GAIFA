import time

import pytest

from store import NotFound, Store

EV = {"kind": "event", "title": "Lunch", "start": "2026-11-13T13:00", "end": "2026-11-13T14:00", "tz": "America/New_York"}


@pytest.fixture
def store(tmp_path):
    return Store(str(tmp_path / "c.db"))


def test_calendars(store):
    d = store.default_calendar()
    w = store.add_calendar("Work")
    assert store.find_calendar("work")["id"] == w["id"] and store.find_calendar(None)["id"] == d["id"]
    store.patch_calendar(w["id"], {"is_default": True, "hidden": True, "color": "#123456"})
    assert store.default_calendar()["id"] == w["id"] and store.calendar(w["id"])["hidden"]
    with pytest.raises(NotFound):
        store.find_calendar("nope")


def test_delete_calendar_moves_or_trashes(store):
    w = store.add_calendar("Work")
    i = store.insert({**EV, "calendar_id": w["id"]})
    with pytest.raises(ValueError):
        store.delete_calendar(w["id"], "")
    store.delete_calendar(w["id"], f"move:{store.default_calendar()['id']}")
    assert store.get(i["id"])["calendar_id"] == store.default_calendar()["id"]
    w2 = store.add_calendar("Old")
    j = store.insert({**EV, "calendar_id": w2["id"]})
    store.delete_calendar(w2["id"], "trash")
    assert [t["id"] for t in store.trash()] == [j["id"]]
    with pytest.raises(ValueError):
        store.delete_calendar(store.default_calendar()["id"], "trash")


def test_crud_trash_restore_purge(store):
    i = store.insert({**EV, "calendar_id": store.default_calendar()["id"], "alerts": [{"before_min": 10}]})
    assert i["alerts"] == [{"before_min": 10}] and not i["all_day"]
    store.update(i["id"], {"title": "Lunch w/ Sam"})
    assert store.search("sam")[0]["id"] == i["id"]
    store.update(i["id"], {"deleted_at": time.time() - 31 * 86400})
    with pytest.raises(NotFound):
        store.get(i["id"])
    assert store.get(i["id"], trashed=True)["title"] == "Lunch w/ Sam"
    assert store.purge() == 1 and store.trash() == []


def test_project_items(store):
    cid = store.default_calendar()["id"]
    a = store.insert({**EV, "calendar_id": cid, "project_id": "p_1"})
    store.insert({**EV, "calendar_id": cid})
    assert [x["id"] for x in store.items(project="p_1")] == [a["id"]]


def test_undo_create_patch_trash(store):
    cid = store.default_calendar()["id"]
    a = store.insert({**EV, "calendar_id": cid})
    u1 = store.record_undo([{"id": a["id"], "row": None, "overrides": {}}])
    snap = store.snapshot([a["id"]])
    store.update(a["id"], {"title": "Changed"})
    store.set_override(a["id"], "2026-11-13T13:00", {"title": "x"})
    u2 = store.record_undo(snap)
    rev = store.rev
    store.undo(u2)
    assert store.get(a["id"])["title"] == "Lunch" and store.overrides(a["id"]) == {} and store.rev > rev
    assert store.undo(u2) == []                          # once
    store.undo(u1)
    with pytest.raises(NotFound):
        store.get(a["id"], trashed=True)
