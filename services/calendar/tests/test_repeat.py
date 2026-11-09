from datetime import datetime
from zoneinfo import ZoneInfo

import repeat as R

NY = ZoneInfo("America/New_York")


def item(**kw):
    base = {"id": "c_1", "kind": "event", "title": "X", "start": "2026-11-02T09:00", "end": "2026-11-02T10:00",
            "all_day": False, "tz": "America/New_York", "rrule": None, "exdates": [], "calendar_id": "cal_1"}
    return {**base, **kw}


def keys(it, frm, to, ovs=None):
    return [o["occurrence"] for o in R.occurrences(it, ovs or {}, datetime(*frm, tzinfo=NY), datetime(*to, tzinfo=NY))]


def test_daily_weekly_count_until():
    assert keys(item(rrule="FREQ=DAILY;COUNT=3"), (2026, 11, 1), (2026, 11, 30)) == \
        ["2026-11-02T09:00", "2026-11-03T09:00", "2026-11-04T09:00"]
    wk = item(rrule="FREQ=WEEKLY;BYDAY=TU,TH;UNTIL=20261112T235959")
    assert keys(wk, (2026, 11, 1), (2026, 12, 1)) == ["2026-11-03T09:00", "2026-11-05T09:00", "2026-11-10T09:00", "2026-11-12T09:00"]


def test_monthly_by_day_and_last_day_and_31st():
    assert keys(item(start="2026-01-31T09:00", end="2026-01-31T10:00", rrule="FREQ=MONTHLY"), (2026, 1, 1), (2026, 5, 1)) == \
        ["2026-01-31T09:00", "2026-03-31T09:00"]                 # RFC 5545: no 31st, no occurrence
    assert keys(item(start="2026-01-31T09:00", end="2026-01-31T10:00", rrule="FREQ=MONTHLY;BYMONTHDAY=-1"),
                (2026, 1, 1), (2026, 4, 1)) == ["2026-01-31T09:00", "2026-02-28T09:00", "2026-03-31T09:00"]


def test_yearly_all_day():
    it = item(start="2026-01-05", end="2026-01-06", all_day=True, rrule="FREQ=YEARLY")
    occ = R.occurrences(it, {}, datetime(2026, 12, 1, tzinfo=NY), datetime(2027, 2, 1, tzinfo=NY))
    assert [(o["start"], o["end"], o["all_day"]) for o in occ] == [("2027-01-05", "2027-01-06", True)]


def test_exdate_and_overrides():
    it = item(rrule="FREQ=DAILY;COUNT=4", exdates=["2026-11-03T09:00"])
    ovs = {"2026-11-04T09:00": {"fields": {"title": "Moved", "start": "2026-11-04T15:00", "end": "2026-11-04T16:00"}, "cancelled": False},
           "2026-11-05T09:00": {"fields": {}, "cancelled": True}}
    occ = R.occurrences(it, ovs, datetime(2026, 11, 1, tzinfo=NY), datetime(2026, 11, 30, tzinfo=NY))
    assert [(o["occurrence"], o["start"], o["title"]) for o in occ] == \
        [("2026-11-02T09:00", "2026-11-02T09:00", "X"), ("2026-11-04T09:00", "2026-11-04T15:00", "Moved")]


def test_moved_into_range_counts():
    it = item(rrule="FREQ=WEEKLY;COUNT=3")
    ovs = {"2026-11-09T09:00": {"fields": {"start": "2026-11-20T09:00", "end": "2026-11-20T10:00"}, "cancelled": False}}
    occ = R.occurrences(it, ovs, datetime(2026, 11, 19, tzinfo=NY), datetime(2026, 11, 21, tzinfo=NY))
    assert [o["start"] for o in occ] == ["2026-11-20T09:00"]


def test_dst_keeps_wall_time():
    it = item(start="2026-10-30T09:00", end="2026-10-30T10:00", rrule="FREQ=DAILY;COUNT=4")
    occ = R.occurrences(it, {}, datetime(2026, 10, 29, tzinfo=NY), datetime(2026, 11, 5, tzinfo=NY))
    assert [o["start"][11:] for o in occ] == ["09:00"] * 4
    assert occ[2]["ts"] - occ[1]["ts"] == 25 * 3600          # Nov 1: the clocks went back


def test_other_zone_shows_in_local():
    it = item(start="2026-11-10T09:00", end="2026-11-10T10:00", tz="Europe/London")
    occ = R.occurrences(it, {}, datetime(2026, 11, 10, tzinfo=NY), datetime(2026, 11, 11, tzinfo=NY))
    assert occ[0]["start"] == "2026-11-10T04:00"


def test_todo_occurrences_and_done():
    it = item(kind="todo", start=None, end=None, due="2026-11-03T18:00", rrule="FREQ=WEEKLY")
    ovs = {"2026-11-03T18:00": {"fields": {"done_at": 1.0}, "cancelled": False}}
    occ = R.occurrences(it, ovs, datetime(2026, 11, 1, tzinfo=NY), datetime(2026, 11, 15, tzinfo=NY))
    assert [(o["due"], o["done"]) for o in occ] == [("2026-11-03T18:00", True), ("2026-11-10T18:00", False)]


def test_split_until_and_count():
    it = item(rrule="FREQ=DAILY")
    old, new = R.split(it, "2026-11-05T09:00")
    assert old == "FREQ=DAILY;UNTIL=20261105T085959" and new == "FREQ=DAILY"
    it = item(rrule="FREQ=DAILY;COUNT=10")
    assert R.split(it, "2026-11-05T09:00") == ("FREQ=DAILY;COUNT=3", "FREQ=DAILY;COUNT=7")
    assert R.split(it, "2026-11-02T09:00")[0] is None
    ad = item(start="2026-11-02", end="2026-11-03", all_day=True, rrule="FREQ=DAILY")
    assert R.split(ad, "2026-11-05")[0] == "FREQ=DAILY;UNTIL=20261104"


def test_next_occurrence():
    it = item(rrule="FREQ=MONTHLY;BYMONTHDAY=1", start="2026-01-01T09:00", end="2026-01-01T10:00")
    o = R.next_occurrence(it, {}, datetime(2026, 11, 9, tzinfo=NY))
    assert o["occurrence"] == "2026-12-01T09:00"


def test_describe():
    assert R.describe("FREQ=WEEKLY;BYDAY=TU,TH") == "Weekly on Tue, Thu"
    assert R.describe("FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR") == "Every weekday"
    assert R.describe("FREQ=DAILY;INTERVAL=2;COUNT=5") == "Every 2 days, 5 times"
    assert R.describe("FREQ=MONTHLY;BYMONTHDAY=-1") == "Monthly on the last day"
    assert R.describe("FREQ=YEARLY;UNTIL=20271201") == "Yearly until Dec 1, 2027"
    assert R.describe(None) == "Doesn't repeat"
