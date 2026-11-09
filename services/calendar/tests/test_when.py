"""The plain-words parser (calendar plan 1.5). `now` is Monday 2026-11-09 10:30 in New York."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from when import Unreadable, parse

NOW = datetime(2026, 11, 9, 10, 30, tzinfo=ZoneInfo("America/New_York"))
FRI = datetime(2026, 11, 13, 10, 30, tzinfo=ZoneInfo("America/New_York"))

EVENTS = [   # text, title, start, end, rrule
    ("lunch w/ Sam Fri 1pm", "lunch w/ Sam", "2026-11-13T13:00", "2026-11-13T14:00", None),
    ("dentist Nov 14 at 3", "dentist", "2026-11-14T15:00", "2026-11-14T16:00", None),
    ("dentist November 14th at 3:30pm", "dentist", "2026-11-14T15:30", "2026-11-14T16:30", None),
    ("dentist 14 Nov 9am", "dentist", "2026-11-14T09:00", "2026-11-14T10:00", None),
    ("dentist 14th of November 9am", "dentist", "2026-11-14T09:00", "2026-11-14T10:00", None),
    ("party Dec 31, 2026 at 9pm", "party", "2026-12-31T21:00", "2026-12-31T22:00", None),
    ("meeting 2026-11-20 14:00", "meeting", "2026-11-20T14:00", "2026-11-20T15:00", None),
    ("dinner 11/14 7:30pm", "dinner", "2026-11-14T19:30", "2026-11-14T20:30", None),
    ("dinner 11/14/27 7pm", "dinner", "2027-11-14T19:00", "2027-11-14T20:00", None),
    ("call today at noon", "call", "2026-11-09T12:00", "2026-11-09T13:00", None),
    ("movie tonight", "movie", "2026-11-09T20:00", "2026-11-09T21:00", None),
    ("run tomorrow 6am", "run", "2026-11-10T06:00", "2026-11-10T07:00", None),
    ("run tmrw at 7am", "run", "2026-11-10T07:00", "2026-11-10T08:00", None),
    ("visit day after tomorrow at 10", "visit", "2026-11-11T10:00", "2026-11-11T11:00", None),
    ("review next fri 2pm", "review", "2026-11-13T14:00", "2026-11-13T15:00", None),
    ("review this wednesday at 4", "review", "2026-11-11T16:00", "2026-11-11T17:00", None),
    ("1-2pm meeting", "meeting", "2026-11-09T13:00", "2026-11-09T14:00", None),
    ("1pm-2:30pm meeting", "meeting", "2026-11-09T13:00", "2026-11-09T14:30", None),
    ("meeting 10–11am Tue", "meeting", "2026-11-10T10:00", "2026-11-10T11:00", None),
    ("class from 13:00 to 14:15 thursday", "class", "2026-11-12T13:00", "2026-11-12T14:15", None),
    ("workshop from 11am to 1pm sat", "workshop", "2026-11-14T11:00", "2026-11-14T13:00", None),
    ("gym in 3 days 6pm for 90 min", "gym", "2026-11-12T18:00", "2026-11-12T19:30", None),
    ("focus 2pm for 2 hours today", "focus", "2026-11-09T14:00", "2026-11-09T16:00", None),
    ("call for an hour at 4pm wed", "call", "2026-11-11T16:00", "2026-11-11T17:00", None),
    ("sync for 1h 30m at 3pm fri", "sync", "2026-11-13T15:00", "2026-11-13T16:30", None),
    ("break in 30 min", "break", "2026-11-09T11:00", "2026-11-09T12:00", None),
    ("break in 2 hours", "break", "2026-11-09T12:30", "2026-11-09T13:30", None),
    ("late shift midnight sat", "late shift", "2026-11-14T00:00", "2026-11-14T01:00", None),
    ("trip Dec 20 - Dec 27 all day", "trip", "2026-12-20", "2026-12-28", None),
    ("holiday Nov 26 all day", "holiday", "2026-11-26", "2026-11-27", None),
    ("conference next week", "conference", "2026-11-16", "2026-11-17", None),
    ("thesis due the 20th", "thesis", "2026-11-20", "2026-11-21", None),
    ("visit in 2 weeks", "visit", "2026-11-23", "2026-11-24", None),
    ("check-in in 1 month", "check-in", "2026-12-09", "2026-12-10", None),
    ("brunch sunday morning", "brunch", "2026-11-15T09:00", "2026-11-15T10:00", None),
    ("call fri afternoon", "call", "2026-11-13T14:00", "2026-11-13T15:00", None),
    ("team sync every Tuesday at 9am", "team sync", "2026-11-10T09:00", "2026-11-10T10:00", "FREQ=WEEKLY;BYDAY=TU"),
    ("standup every weekday at 9:15", "standup", "2026-11-09T09:15", "2026-11-09T10:15", "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR"),
    ("yoga every mon, wed and fri 7am", "yoga", "2026-11-09T07:00", "2026-11-09T08:00", "FREQ=WEEKLY;BYDAY=MO,WE,FR"),
    ("rent monthly on the 1st", "rent", "2026-12-01", "2026-12-02", "FREQ=MONTHLY;BYMONTHDAY=1"),
    ("rent every month on the 15th", "rent", "2026-11-15", "2026-11-16", "FREQ=MONTHLY;BYMONTHDAY=15"),
    ("review every other week fri 3pm", "review", "2026-11-13T15:00", "2026-11-13T16:00", "FREQ=WEEKLY;INTERVAL=2"),
    ("water plants every 3 days", "water plants", "2026-11-09", "2026-11-10", "FREQ=DAILY;INTERVAL=3"),
    ("birthday every year on Jan 5", "birthday", "2027-01-05", "2027-01-06", "FREQ=YEARLY"),
    ("report weekdays at 5pm", "report", "2026-11-09T17:00", "2026-11-09T18:00", "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR"),
    ("close books every month on the last day", "close books", "2026-11-09", "2026-11-10", "FREQ=MONTHLY;BYMONTHDAY=-1"),
]


@pytest.mark.parametrize("text,title,start,end,rrule", EVENTS)
def test_events(text, title, start, end, rrule):
    p = parse(text, NOW)
    assert (p["title"], p["start"], p["end"], p["rrule"]) == (title, start, end, rrule)


def test_date_order():
    assert parse("study 14/11", NOW, date_order="dmy")["start"] == "2026-11-14"
    assert parse("study 11/12", NOW, date_order="dmy")["start"] == "2026-12-11"
    assert parse("study 11/12", NOW)["start"] == "2026-11-12"


def test_weekday_on_that_day():
    assert parse("lunch fri 1pm", FRI)["start"] == "2026-11-13T13:00"
    assert parse("lunch next fri 1pm", FRI)["start"] == "2026-11-20T13:00"


def test_assumptions_are_said():
    p = parse("dentist fri at 3", NOW)
    assert "3 = 15:00" in p["assumed"] and "no end: 1 hour" in p["assumed"] and p["confidence"] == "assumed"
    assert parse("1pm-2pm meeting nov 20", NOW)["confidence"] == "exact"


def test_todos():
    p = parse("remind me to call the bank tomorrow at 10", NOW)
    assert (p["kind"], p["title"], p["due"]) == ("todo", "call the bank", "2026-11-10T10:00")
    p = parse("buy milk at 9am", NOW, kind="todo")
    assert p["due"] == "2026-11-10T09:00" and any("passed" in a for a in p["assumed"])
    assert parse("buy milk", NOW, kind="todo")["due"] is None
    assert parse("pay rent nov 30", NOW, kind="todo")["due"] == "2026-11-30"


def test_whole_and_unreadable():
    assert parse("fri 1pm for 90 min", NOW, whole=True)["title"] == ""
    with pytest.raises(Unreadable) as e:
        parse("fri after lunchtime", NOW, whole=True)
    assert "lunchtime" in e.value.part
    with pytest.raises(Unreadable):
        parse("sometime soonish", NOW)
    with pytest.raises(Unreadable):
        parse("party feb 30", NOW)
    with pytest.raises(Unreadable):
        parse("", NOW)
