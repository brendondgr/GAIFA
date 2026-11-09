"""Plan scheduled-tasks 1.1: when a task is due, in local time (TZ set per test)."""

from __future__ import annotations

import time

import pytest

from agent.tasks import when


@pytest.fixture(autouse=True)
def tz(monkeypatch):
    monkeypatch.setenv("TZ", "America/New_York")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


def at(y, mo, d, h=0, mi=0):
    return time.mktime((y, mo, d, h, mi, 0, 0, 0, -1))


def local(t):
    return time.strftime("%Y-%m-%d %a %H:%M", time.localtime(t))


def test_check():
    assert when.check({"kind": "daily", "time": "07:00"}) == []
    assert when.check({"kind": "hourly", "every": 2, "minute": 15, "from": "08:00", "to": "18:00", "weekdays": True}) == []
    assert when.check({"kind": "nope"}) and when.check("daily") and when.check({"kind": "daily", "time": "7:00"})
    assert when.check({"kind": "weekly", "day": 7, "time": "07:00"}) and when.check({"kind": "monthly", "day": 0, "time": "07:00"})
    assert when.check({"kind": "hourly", "every": 0}) and when.check({"kind": "hourly", "minute": 60})
    assert when.check({"kind": "hourly", "from": "08:00"})                      # half a window
    assert when.check({"kind": "hourly", "from": "18:00", "to": "08:00"})       # backwards
    assert when.check({"kind": "hourly", "every": 5, "minute": 30, "from": "01:00", "to": "04:00"})   # nothing inside
    assert when.check({"kind": "hourly", "every": True})


def test_daily_weekdays_weekly():
    mon = at(2026, 11, 9, 8, 0)                  # Monday 08:00
    d = {"kind": "daily", "time": "07:00"}
    assert local(when.next_after(d, mon)) == "2026-11-10 Tue 07:00"
    assert local(when.next_after(d, at(2026, 11, 9, 6, 59))) == "2026-11-09 Mon 07:00"
    assert local(when.next_after(d, at(2026, 11, 9, 7, 0))) == "2026-11-10 Tue 07:00"    # strictly after
    wd = {"kind": "weekdays", "time": "07:00"}
    assert local(when.next_after(wd, at(2026, 11, 13, 8))) == "2026-11-16 Mon 07:00"     # Friday → Monday
    wk = {"kind": "weekly", "day": 2, "time": "21:30"}
    assert local(when.next_after(wk, mon)) == "2026-11-11 Wed 21:30"
    assert local(when.next_after(wk, at(2026, 11, 11, 22))) == "2026-11-18 Wed 21:30"


def test_monthly_last_day():
    m = {"kind": "monthly", "day": 31, "time": "09:00"}
    assert local(when.next_after(m, at(2027, 1, 31, 10))) == "2027-02-28 Sun 09:00"
    assert local(when.next_after(m, at(2027, 2, 28, 10))) == "2027-03-31 Wed 09:00"
    assert local(when.next_after(m, at(2028, 2, 1))) == "2028-02-29 Tue 09:00"            # leap year
    assert local(when.next_after({"kind": "monthly", "day": 15, "time": "00:00"}, at(2026, 11, 15, 0, 1))) == "2026-12-15 Tue 00:00"


def test_hourly():
    h = {"kind": "hourly", "every": 2, "minute": 15}
    assert local(when.next_after(h, at(2026, 11, 9, 9, 0))) == "2026-11-09 Mon 10:15"
    assert local(when.next_after(h, at(2026, 11, 9, 23, 0))) == "2026-11-10 Tue 00:15"
    w = {"kind": "hourly", "every": 1, "minute": 0, "from": "08:00", "to": "18:00", "weekdays": True}
    assert local(when.next_after(w, at(2026, 11, 9, 18, 30))) == "2026-11-10 Tue 08:00"
    assert local(when.next_after(w, at(2026, 11, 13, 18, 30))) == "2026-11-16 Mon 08:00"  # skips the weekend
    assert local(when.next_after(w, at(2026, 11, 9, 12, 0))) == "2026-11-09 Mon 13:00"


def test_dst():
    # 2027-03-14: 02:00 → 03:00 in New York. A daily 02:30 has no 02:30 that day: it moves to the next valid minute.
    d = {"kind": "daily", "time": "02:30"}
    t = when.next_after(d, at(2027, 3, 13, 3))
    assert time.localtime(t).tm_mday == 14 and time.localtime(t).tm_hour == 3
    assert local(when.next_after(d, t)) == "2027-03-15 Mon 02:30"
    # 2026-11-01: 01:00–02:00 happens twice. A daily 01:30 runs once.
    d = {"kind": "daily", "time": "01:30"}
    first = when.next_after(d, at(2026, 10, 31, 12))
    assert local(first) == "2026-11-01 Sun 01:30"
    assert local(when.next_after(d, first)) == "2026-11-02 Mon 01:30"


def test_missed():
    d = {"kind": "daily", "time": "07:00"}
    assert when.missed(d, at(2026, 11, 2, 7), at(2026, 11, 9, 8)) == 7
    assert when.missed(d, at(2026, 11, 9, 7), at(2026, 11, 9, 8)) == 0
    assert when.missed({"kind": "hourly", "every": 1, "minute": 0}, 0, at(2026, 11, 9)) == when.MISSED_MAX


def test_describe():
    assert when.describe({"kind": "weekdays", "time": "07:00"}) == "Weekdays at 07:00"
    assert when.describe({"kind": "hourly", "every": 2, "minute": 15, "from": "08:00", "to": "18:00"}) == \
        "Every 2 hours at :15, 08:00–18:00"
    assert when.describe({"kind": "hourly", "every": 1, "minute": 0, "weekdays": True}) == "Every hour at :00, weekdays"
    assert when.describe({"kind": "weekly", "day": 0, "time": "09:00"}) == "Mondays at 09:00"
    assert when.describe({"kind": "monthly", "day": 31, "time": "09:00"}) == "Monthly on the 31st at 09:00 (or the month's last day)"
    assert when.describe({"kind": "monthly", "day": 12, "time": "09:00"}) == "Monthly on the 12th at 09:00"
    assert when.describe({"kind": "daily", "time": "21:00"}) == "Every day at 21:00"
