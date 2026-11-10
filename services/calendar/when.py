"""Dates and times in plain words (calendar plan 1.5): a small deterministic grammar, no model.

`parse(text, now, kind, date_order, whole)` reads the date, time, length and repeat out of a phrase like
"lunch w/ Sam Fri 1pm for 90 min" and returns them with the rest of the text as the title, plus what it had to
assume ("no end: 1 hour"). With `whole=True` (a `when` field) every word must be read, else `Unreadable`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

import timeutil as T

MONTHS = {m: i + 1 for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
MONTH_RE = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?"
WD = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
WD_RE = r"(mon(?:day)?|tue(?:s(?:day)?)?|wed(?:nesday)?|thu(?:r(?:s(?:day)?)?)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?)"
RR_DAYS = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]
ORD = r"(\d{1,2})(?:st|nd|rd|th)?"
T_RE = r"(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.|a|p)?"
CONNECT = {"on", "at", "from", "to", "for", "by", "due", "until", "starting", "the", "in", "of", "@", "-", "–", ",", "and"}


class Unreadable(ValueError):
    def __init__(self, detail: str, part: str) -> None:
        super().__init__(detail)
        self.part = part


@dataclass
class Found:
    day: date | None = None
    time: tuple[int, int] | None = None
    end_time: tuple[int, int] | None = None
    end_day: date | None = None
    length: timedelta | None = None
    all_day: bool = False
    rrule: str | None = None
    at: datetime | None = None          # an exact moment ("in 2 hours")
    spans: list[tuple[int, int]] = field(default_factory=list)
    assumed: list[str] = field(default_factory=list)


def _wd(s: str) -> int:
    return WD.index(s[:3].lower())


def _month(s: str) -> int:
    return MONTHS[s[:3].lower()]


def _hour(h: int, m: int, ap: str | None, found: Found, word: str) -> tuple[int, int]:
    ap = (ap or "").replace(".", "").lower()[:1]
    if h > 23 or m > 59:
        raise Unreadable(f"{word!r} isn't a time", word)
    if ap == "p" and h < 12:
        h += 12
    elif ap == "a" and h == 12:
        h = 0
    elif not ap and 1 <= h <= 7:
        h += 12
        found.assumed.append(f"{word.strip()} = {h:02d}:{m:02d}")
    return h, m


def _year_for(month: int, day: int, today: date) -> int:
    y = today.year
    try:
        if date(y, month, day) < today - timedelta(days=31):     # well past: next year's
            y += 1
    except ValueError:
        pass
    return y


class _Scan:
    def __init__(self, text: str, now: datetime, date_order: str) -> None:
        self.text = text
        self.low = text.lower()
        self.now = now
        self.today = now.date()
        self.order = date_order
        self.f = Found()

    def take(self, pattern: str, fn: Any) -> None:
        for m in list(re.finditer(pattern, self.low, re.I)):
            if any(a < m.end() and m.start() < b for a, b in self.f.spans):
                continue
            if fn(m) is not False:
                self.f.spans.append((m.start(), m.end()))

    def run(self) -> Found:
        f = self.f
        B = r"(?<![\w/:])"
        E = r"(?![\w/:])"
        # repeats first: their words name days too
        self.take(B + r"every\s+(other\s+)?(\d+\s+)?(day|weekday|week|month|year)s?(?:\s+on\s+the\s+" + ORD + r"|\s+on\s+the\s+last\s+day)?" + E, self._every_unit)
        self.take(B + r"every\s+" + WD_RE + r"(?:\s*(?:,|and|&)\s*" + WD_RE + r")*" + E, self._every_days)
        self.take(B + r"(daily|weekly|monthly|yearly|annually|weekdays)(?:\s+on\s+the\s+" + ORD + r")?" + E, self._every_word)
        self.take(B + r"all[\s-]day" + E, lambda m: setattr(f, "all_day", True))
        # lengths
        self.take(B + r"for\s+(\d+)\s*h(?:ours?)?\s*(\d+)\s*m(?:in(?:ute)?s?)?" + E, self._length2)
        self.take(B + r"for\s+(an?|\d+(?:\.\d+)?)\s*(h|hr|hrs|hours?|m|mins?|minutes?)" + E, self._length)
        # relative moments
        self.take(B + r"in\s+(an?|\d+)\s*(min(?:ute)?s?|hours?|hrs?|days?|weeks?|months?)" + E, self._in)
        # dates
        self.take(B + r"(\d{4})-(\d{2})-(\d{2})" + E, lambda m: self._set_day(date(int(m[1]), int(m[2]), int(m[3]))))
        self.take(B + r"(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?" + E, self._numeric)
        self.take(B + MONTH_RE + r"\s+" + ORD + r"(?:,?\s+(\d{4}))?" + E, self._month_day)
        self.take(B + ORD + r"(?:\s+of)?\s+" + MONTH_RE + r"(?:,?\s+(\d{4}))?" + E, self._day_month)
        self.take(B + r"(day after tomorrow|today|tonight|tomorrow|tmrw|tmr|yesterday)" + E, self._named)
        self.take(B + r"next\s+week" + E, self._next_week)
        self.take(B + r"(next|this)\s+" + WD_RE + E, self._weekday)
        self.take(B + WD_RE + E, self._weekday)
        self.take(B + r"the\s+" + r"(\d{1,2})(?:st|nd|rd|th)" + E, self._the_nth)
        # times: ranges first
        self.take(B + r"(?:from\s+)?" + T_RE + r"\s*(?:-|–|to|until|till)\s*" + T_RE + E, self._range)
        self.take(B + r"(noon|midday|midnight)" + E, self._named_time)
        self.take(B + r"(\d{1,2}):(\d{2})\s*(am|pm|a\.m\.|p\.m\.)?" + E, self._time)
        self.take(B + r"(\d{1,2})\s*(am|pm|a\.m\.|p\.m\.)" + E, lambda m: self._time_parts(int(m[1]), 0, m[2], m[0]))
        self.take(B + r"(?:at|@)\s*(\d{1,2})" + E, lambda m: self._time_parts(int(m[1]), 0, None, m[1]))
        self.take(B + r"(morning|afternoon|evening|night)" + E, self._part_of_day)
        return f

    # -- repeats ---------------------------------------------------------------------------------------------
    def _every_unit(self, m: re.Match[str]) -> None:
        n = 2 if m[1] else int(m[2]) if m[2] else 1
        unit = m[3]
        rule = {"day": "FREQ=DAILY", "weekday": "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR", "week": "FREQ=WEEKLY",
                "month": "FREQ=MONTHLY", "year": "FREQ=YEARLY"}[unit]
        if n > 1 and unit != "weekday":
            rule += f";INTERVAL={n}"
        if m[4]:
            rule += f";BYMONTHDAY={int(m[4])}"
            self._set_day(self._next_monthday(int(m[4])), soft=True)
        elif "last day" in m[0]:
            rule += ";BYMONTHDAY=-1"
        self.f.rrule = rule
        if unit == "weekday":
            self._first_matching([0, 1, 2, 3, 4])

    def _every_days(self, m: re.Match[str]) -> None:
        days = sorted({_wd(x) for x in re.findall(WD_RE, m[0], re.I)})
        self.f.rrule = "FREQ=WEEKLY;BYDAY=" + ",".join(RR_DAYS[d] for d in days)
        self._first_matching(days)

    def _every_word(self, m: re.Match[str]) -> None:
        w = m[1].lower()
        if w == "weekdays":
            self.f.rrule = "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR"
            self._first_matching([0, 1, 2, 3, 4])
            return
        self.f.rrule = {"daily": "FREQ=DAILY", "weekly": "FREQ=WEEKLY", "monthly": "FREQ=MONTHLY",
                        "yearly": "FREQ=YEARLY", "annually": "FREQ=YEARLY"}[w]
        if m[2]:
            self.f.rrule += f";BYMONTHDAY={int(m[2])}"
            self._set_day(self._next_monthday(int(m[2])), soft=True)

    def _first_matching(self, days: list[int]) -> None:
        if self.f.day is None:
            d = self.today
            while d.weekday() not in days:
                d += timedelta(days=1)
            self.f.day = d

    def _next_monthday(self, n: int) -> date:
        d = self.today
        for _ in range(62):
            if d.day == n:
                return d
            d += timedelta(days=1)
        raise Unreadable(f"no month has a day {n}", str(n))

    # -- lengths and moments ---------------------------------------------------------------------------------
    def _length(self, m: re.Match[str]) -> None:
        n = 1.0 if m[1] in ("a", "an") else float(m[1])
        self.f.length = timedelta(hours=n) if m[2].startswith("h") else timedelta(minutes=n)

    def _length2(self, m: re.Match[str]) -> None:
        self.f.length = timedelta(hours=int(m[1]), minutes=int(m[2]))

    def _in(self, m: re.Match[str]) -> None:
        n = 1 if m[1] in ("a", "an") else int(m[1])
        u = m[2][:2]
        if u in ("mi", "ho", "hr"):
            self.f.at = self.now + (timedelta(minutes=n) if u == "mi" else timedelta(hours=n))
        elif u == "da":
            self._set_day(self.today + timedelta(days=n))
        elif u == "we":
            self._set_day(self.today + timedelta(weeks=n))
        else:
            mo = self.today.month - 1 + n
            y, mo = self.today.year + mo // 12, mo % 12 + 1
            self._set_day(_clamp(y, mo, self.today.day))

    # -- dates -----------------------------------------------------------------------------------------------
    def _set_day(self, d: date, soft: bool = False) -> None:
        if self.f.day is not None and not soft and self.f.day != d:
            if self.f.end_day is None and d > self.f.day:
                self.f.end_day = d
                return
        if self.f.day is None or not soft:
            self.f.day = d

    def _numeric(self, m: re.Match[str]) -> bool | None:
        a, b = int(m[1]), int(m[2])
        mo, dy = (a, b) if self.order == "mdy" else (b, a)
        if not (1 <= mo <= 12 and 1 <= dy <= 31):
            return False
        y = int(m[3]) if m[3] else _year_for(mo, dy, self.today)
        if y < 100:
            y += 2000
        try:
            self._set_day(date(y, mo, dy))
        except ValueError:
            raise Unreadable(f"{m[0]!r} isn't a date", m[0]) from None
        return None

    def _month_day(self, m: re.Match[str]) -> None:
        mo, dy = _month(m[1]), int(m[2])
        y = int(m[3]) if m[3] else _year_for(mo, dy, self.today)
        try:
            self._set_day(date(y, mo, dy))
        except ValueError:
            raise Unreadable(f"{m[0]!r} isn't a date", m[0]) from None

    def _day_month(self, m: re.Match[str]) -> None:
        dy, mo = int(m[1]), _month(m[2])
        y = int(m[3]) if m[3] else _year_for(mo, dy, self.today)
        try:
            self._set_day(date(y, mo, dy))
        except ValueError:
            raise Unreadable(f"{m[0]!r} isn't a date", m[0]) from None

    def _named(self, m: re.Match[str]) -> None:
        w = m[1].lower()
        d = {"today": 0, "tonight": 0, "tomorrow": 1, "tmrw": 1, "tmr": 1, "yesterday": -1, "day after tomorrow": 2}[w]
        self._set_day(self.today + timedelta(days=d))
        if w == "tonight" and self.f.time is None:
            self.f.time = (20, 0)
            self.f.assumed.append("tonight = 20:00")

    def _next_week(self, m: re.Match[str]) -> None:
        d = self.today + timedelta(days=7 - self.today.weekday())
        self._set_day(d)
        self.f.assumed.append(f"next week = Mon {d.strftime('%b')} {d.day}")

    def _weekday(self, m: re.Match[str]) -> None:
        g = m.groups()
        nxt = len(g) == 2 and (g[0] or "").lower() == "next"
        wd = _wd(g[-1])
        ahead = (wd - self.today.weekday()) % 7
        if nxt and ahead == 0:
            ahead = 7
        d = self.today + timedelta(days=ahead)
        self._set_day(d)
        if nxt or ahead:
            self.f.assumed.append(f"{m[0].strip()} = {d.strftime('%a %b')} {d.day}")

    def _the_nth(self, m: re.Match[str]) -> None:
        self._set_day(self._next_monthday(int(m[1])))

    # -- times -----------------------------------------------------------------------------------------------
    def _range(self, m: re.Match[str]) -> bool | None:
        h1, m1, a1, h2, m2, a2 = m[1], m[2], m[3], m[4], m[5], m[6]
        if not (a1 or a2 or m1 or m2):           # "1-2" alone is too vague (could be a date part)
            if not re.search(r"(from|at)\s", m[0]):
                return False
        a1 = a1 or (a2 if a2 and int(h1) <= int(h2) % 12 + (12 if int(h2) == 12 else 0) else None)
        start = _hour(int(h1), int(m1 or 0), a1, self.f, m[0])
        end = _hour(int(h2), int(m2 or 0), a2, self.f, m[0])
        if end <= start and not a2 and end[0] < 12:
            end = (end[0] + 12, end[1])
        self.f.time, self.f.end_time = start, end
        return None

    def _named_time(self, m: re.Match[str]) -> None:
        self.f.time = (0, 0) if m[1].lower() == "midnight" else (12, 0)

    def _time(self, m: re.Match[str]) -> None:
        self._time_parts(int(m[1]), int(m[2]), m[3], m[0])

    def _time_parts(self, h: int, mi: int, ap: str | None, word: str) -> bool | None:
        if self.f.time is not None:
            return False
        self.f.time = _hour(h, mi, ap, self.f, word)
        return None

    def _part_of_day(self, m: re.Match[str]) -> bool | None:
        if self.f.time is not None:
            return None                           # "tomorrow morning at 8": the time wins
        t = {"morning": (9, 0), "afternoon": (14, 0), "evening": (18, 0), "night": (20, 0)}[m[1].lower()]
        self.f.time = t
        self.f.assumed.append(f"{m[1].lower()} = {t[0]:02d}:00")
        return None


def _clamp(y: int, mo: int, d: int) -> date:
    while True:
        try:
            return date(y, mo, d)
        except ValueError:
            d -= 1


def _leftover(text: str, spans: list[tuple[int, int]]) -> str:
    keep = []
    last = 0
    for a, b in sorted(spans):
        keep.append(text[last:a])
        last = b
    keep.append(text[last:])
    words = " ".join(keep).split()
    # drop connector words left at the edges or doubled up by the cut ("lunch on at" → "lunch")
    while words and words[-1].lower().strip(",.;:") in CONNECT:
        words.pop()
    while words and words[0].lower().strip(",.;:") in CONNECT - {"the"}:
        words.pop(0)
    out = " ".join(words)
    out = re.sub(r"\s+([,.;:])", r"\1", out)
    out = re.sub(r"\b(on|at|from|for|by|due)\s+(?=(on|at|from|for|by|due)\b)", "", out, flags=re.I)
    return out.strip(" ,.;:-–")


REMIND = re.compile(r"^\s*(?:please\s+)?(?:remind\s+me\s+(?:to\s+)?|reminder\s*:?\s*(?:to\s+)?|todo\s*:?\s*|to-do\s*:?\s*)", re.I)


def parse(text: str, now: datetime | None = None, kind: str = "event", date_order: str = "mdy",
          whole: bool = False) -> dict[str, Any]:
    """What `text` says (see the module docstring). Times are wall strings in this machine's zone."""
    now = now or T.now_local()
    text = text.strip()
    if not text:
        raise Unreadable("there's nothing to read", "")
    is_remind = bool(REMIND.match(text))
    if is_remind and kind == "event":
        kind = "todo"
    body = REMIND.sub("", text)
    f = _Scan(body, now, date_order).run()
    title = _leftover(body, f.spans)
    if whole and title:
        bad = [w for w in title.split() if w.lower().strip(",.") not in CONNECT]
        if bad:
            raise Unreadable(f"couldn't read {' '.join(bad)!r} as a date or time", " ".join(bad))
    if not (f.day or f.time or f.at or f.rrule or f.all_day):
        if whole or kind == "event":
            raise Unreadable(f"no date or time in {text!r}", text)
    out: dict[str, Any] = {"kind": kind, "title": title, "all_day": False, "rrule": f.rrule,
                           "matched": [body[a:b] for a, b in sorted(f.spans)], "assumed": list(f.assumed)}
    start: datetime | None = None
    day = f.day
    if f.at is not None:
        start = f.at.replace(tzinfo=None, second=0, microsecond=0)
    elif f.time is not None:
        if day is None:
            day = now.date()
            cand = datetime.combine(day, datetime.min.time()).replace(hour=f.time[0], minute=f.time[1])
            if kind == "todo" and cand < now.replace(tzinfo=None):
                day = day + timedelta(days=1)
                out["assumed"].append(f"{f.time[0]:02d}:{f.time[1]:02d} has passed today: tomorrow")
        start = datetime.combine(day, datetime.min.time()).replace(hour=f.time[0], minute=f.time[1])
    if kind == "todo":
        if start is not None:
            out["due"] = T.fmt_wall(start)
        elif day is not None:
            out["due"] = day.isoformat()
            out["all_day"] = True
        else:
            out["due"] = None
        out["confidence"] = "assumed" if out["assumed"] else "exact"
        return out
    if start is None:                                    # an all-day event
        if day is None:
            day = now.date()
            out["assumed"].append("no date: today")
        end_day = (f.end_day or day) + timedelta(days=1)
        out.update(start=day.isoformat(), end=end_day.isoformat(), all_day=True)
    else:
        if f.end_time is not None:
            end = datetime.combine((f.end_day or start.date()), datetime.min.time()).replace(hour=f.end_time[0], minute=f.end_time[1])
            if end <= start:
                end += timedelta(days=1)
        elif f.length is not None:
            end = start + f.length
        else:
            end = start + timedelta(hours=1)
            out["assumed"].append("no end: 1 hour")
        out.update(start=T.fmt_wall(start), end=T.fmt_wall(end))
    out["confidence"] = "assumed" if out["assumed"] else "exact"
    return out
