"""Numbers as words, for speaking. The model says "one hundred five" right and often garbles "105" (measured:
the same sentence with digits came back wrong in three places, with words in none). English only."""

from __future__ import annotations

import re

ONES = ("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen "
        "seventeen eighteen nineteen").split()
TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()
SCALES = ((10 ** 12, "trillion"), (10 ** 9, "billion"), (10 ** 6, "million"), (1000, "thousand"))
ORDINALS = {"one": "first", "two": "second", "three": "third", "five": "fifth", "eight": "eighth", "nine": "ninth",
            "twelve": "twelfth"}

_TIME = re.compile(r"(?<![\w:.])([01]?\d|2[0-3]):([0-5]\d)(?![\w:])")
_MONEY = re.compile(r"\$\s?(\d[\d,]*(?:\.\d+)?)")
_ORDINAL = re.compile(r"(?<![\w.,])(\d{1,6})(?:st|nd|rd|th)\b")
_NUMBER = re.compile(r"(?<![\w.,])(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?(?![\d]|\.\d|,\d)")


def integer(n: int) -> str:
    if n < 20:
        return ONES[n]
    if n < 100:
        return TENS[n // 10] + ("-" + ONES[n % 10] if n % 10 else "")
    if n < 1000:
        return ONES[n // 100] + " hundred" + (" " + integer(n % 100) if n % 100 else "")
    for size, name in SCALES:
        if n >= size:
            return integer(n // size) + " " + name + (" " + integer(n % size) if n % size else "")
    return str(n)


def year(n: int) -> str:
    if 2000 <= n <= 2009:
        return integer(n)
    return integer(n // 100) + " " + ("hundred" if n % 100 == 0 else ("oh " if n % 100 < 10 else "") + integer(n % 100))


def ordinal(n: int) -> str:
    words = integer(n)
    head, sep, last = words.rpartition("-") if "-" in words.split(" ")[-1] else words.rpartition(" ")
    if last in ORDINALS:
        last = ORDINALS[last]
    elif last.endswith("y"):
        last = last[:-1] + "ieth"
    else:
        last += "th"
    return head + sep + last


def _number(m: re.Match) -> str:
    whole, frac = m.group(1), m.group(2)
    digits = whole.replace(",", "")
    if len(digits) > 15:
        return " ".join(ONES[int(d)] for d in digits)
    n = int(digits)
    if frac:
        return integer(n) + " point " + " ".join(ONES[int(d)] for d in frac[1:])
    if "," not in whole and len(digits) == 4 and 1100 <= n <= 2099:
        return year(n)
    if len(digits) > 1 and digits[0] == "0":                      # a code, not a quantity: digit by digit
        return " ".join(ONES[int(d)] for d in digits)
    return integer(n)


def _time(m: re.Match) -> str:
    h, mi = int(m.group(1)), int(m.group(2))
    return integer(h) + ("" if mi == 0 else " oh " + integer(mi) if mi < 10 else " " + integer(mi))


def spoken_numbers(text: str) -> str:
    s = _TIME.sub(_time, text)
    s = _MONEY.sub(lambda m: m.group(1) + " dollars", s)
    s = re.sub(r"(?<=\d)\s*%", " percent", s)
    s = _ORDINAL.sub(lambda m: ordinal(int(m.group(1))), s)
    s = _NUMBER.sub(_number, s)
    return re.sub(r"(?<=[a-z])(?=[A-Z]{2})", " ", s)              # "fiveGB" → "five GB"
