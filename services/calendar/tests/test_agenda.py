"""calendar 5.1: the agenda's text for the prompt: today, to-dos due and overdue, tomorrow, a project's dates, the
cap, the setting off, and the same text all day."""

from datetime import date
from unittest import mock

import agenda


def add(client, **kw):
    r = client.post("/v1/items", json=kw)
    assert r.status_code == 200, r.text
    return r.json()["item"]


def text(client, d="2026-11-09", project=None):
    return client.get("/v1/agenda/prompt", params={"date": d, **({"project": project} if project else {})}).json()["text"]


def test_sections(client):
    s = add(client, title="Standup", when="2026-11-09 9:15am for 15 min", repeat="every weekday")
    add(client, title="Dentist", when="2026-11-09 3pm")
    add(client, title="Trip", start="2026-11-10", end="2026-11-12")
    add(client, kind="todo", title="Call the bank", due="2026-11-09T10:00")
    add(client, kind="todo", title="Library books", due="2026-11-05")
    t = text(client)
    assert t.splitlines()[0] == "Today, Mon 9 Nov:"
    assert f"- 09:15–09:30 Standup (Personal) ↻ [{s['id']}]" in t
    assert "To-dos due today and overdue:" in t and "to-do, due 10:00: Call the bank" in t and "Thu 5 Nov overdue to-do: Library books" in t
    tomorrow = t.split("Tomorrow, Tue 10 Nov:")[1]
    assert "all day: Trip" in tomorrow and "09:15–09:30 Standup" in tomorrow and "Dentist" not in tomorrow


def test_nothing_and_project_and_off(client):
    assert text(client, "2030-01-01") == "Today, Tue 1 Jan:\n- nothing\nTomorrow, Wed 2 Jan:\n- nothing"
    add(client, title="Thesis draft due", start="2030-01-10", project_id="p_thesis")
    assert "This project's dates (next 14 days):\n- Thu 10 Jan all day: Thesis draft due" in text(client, "2030-01-01", "p_thesis")
    assert "project" not in text(client, "2030-01-01")
    client.patch("/v1/settings", json={"agenda_in_prompt": False})
    assert text(client) == ""


def test_the_cap(client):
    for i in range(50):
        add(client, title=f"Slot {i}", when=f"2030-01-01 {8 + i // 6}:{(i % 6) * 10:02d}am" if 8 + i // 6 < 12 else f"2030-01-01 {8 + i // 6 - 12 or 12}:{(i % 6) * 10:02d}pm")
    lines = text(client, "2030-01-01").splitlines()
    assert len(lines) == agenda.MAX_LINES and lines[-1].startswith("- … and ")


def test_same_text_morning_and_evening(client, cal):
    add(client, title="Dentist", when="2026-11-09 3pm")
    add(client, kind="todo", title="Call the bank", due="2026-11-09T10:00")
    from datetime import datetime
    from zoneinfo import ZoneInfo
    texts = []
    for h in (8, 20):
        with mock.patch("timeutil.now_local", return_value=datetime(2026, 11, 9, h, tzinfo=ZoneInfo("America/New_York"))):
            texts.append(agenda.prompt_text(cal.items, cal.settings.get(), date(2026, 11, 9)))
    assert texts[0] == texts[1]
