"""Scoring for the size comparison (plan voice-speech-model 4.1): pure functions, no model."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

NUMBERS = {"zero": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7", "eight": "8",
           "nine": "9", "ten": "10", "eleven": "11", "twelve": "12", "twenty": "20", "thirty": "30", "forty": "40", "fifty": "50",
           "hundred": "100"}
SPELLING = {"favourite": "favorite", "colour": "color", "centre": "center", "metres": "meters", "kilometres": "kilometers"}


def words(text: str) -> list[str]:
    """Lower-case words without punctuation or accents; small numbers as digits ("forty-two" → 40 2), so a
    transcript that writes 42 as words isn't counted wrong for it, and British spellings as American."""
    t = unicodedata.normalize("NFKD", text.lower().replace("’", "'"))
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"(\d)[,.](\d{3})\b", r"\1\2", t)
    out: list[str] = []
    for w in re.findall(r"[a-z0-9']+", t.replace("-", " ")):
        w = w.strip("'")
        if not w:
            continue
        w = SPELLING.get(NUMBERS.get(w, w), NUMBERS.get(w, w))
        if w.isdigit() and len(w) == 2 and w[1] != "0" and int(w) > 20:      # 42 → 40 2, as the words read
            out += [w[0] + "0", w[1]]
        else:
            out.append(w)
    return out


def wer(reference: str, hypothesis: str) -> float:
    """Word error rate: the word edits to turn the hypothesis into the reference, over the reference's length."""
    r, h = words(reference), words(hypothesis)
    if not r:
        return 0.0 if not h else 1.0
    prev = list(range(len(h) + 1))
    for i, rw in enumerate(r, 1):
        cur = [i]
        for j, hw in enumerate(h, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (rw != hw)))
        prev = cur
    return prev[-1] / len(r)


def has_all(answer: str, expect: list[str]) -> bool:
    """Every expected word (or one of its | alternatives) is in the answer."""
    got = " ".join(words(answer))
    return all(any(" ".join(words(alt)) in got for alt in e.split("|")) for e in expect)


def pct(values: list[float], q: float) -> float | None:
    v = sorted(x for x in values if x is not None)
    if not v:
        return None
    return v[min(len(v) - 1, int(round(q * (len(v) - 1))))]


def summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """One size's numbers over its turns (`rows`: one per prompt, as compare.py records them)."""
    ok = [r for r in rows if not r.get("error")]
    first = [r["first_audio_ms"] for r in ok if r.get("first_audio_ms") is not None]
    speed = [r["reply_s"] / (r["audio_ms"] / 1000) for r in ok if r.get("audio_ms") and r.get("reply_s")]
    heard = [r["heard_wer"] for r in ok if r.get("heard_wer") is not None]
    spoken = [r["spoken_wer"] for r in ok if r.get("spoken_wer") is not None]
    right = [r["right"] for r in ok if r.get("right") is not None]
    mean = lambda v: sum(v) / len(v) if v else None  # noqa: E731
    return {"turns": len(rows), "failed": len(rows) - len(ok), "first_audio_ms": pct(first, 0.5), "first_audio_p90_ms": pct(first, 0.9),
            "speed": mean(speed), "heard_wer": mean(heard), "spoken_wer": mean(spoken),
            "right": (sum(right), len(right)) if right else None}


def fmt(v: Any, kind: str = "") -> str:
    if v is None:
        return "—"
    if kind == "pct":
        return f"{v * 100:.1f} %"
    if kind == "ms":
        return f"{v:.0f} ms"
    if kind == "x":
        return f"{1 / v:.1f}× real time" if v else "—"
    if kind == "gb":
        return f"{v / 1e9:.1f} GB"
    if kind == "of":
        return f"{v[0]} of {v[1]}"
    return str(v)


def table(sizes: dict[str, dict[str, Any]]) -> str:
    """The comparison as a markdown table: a row per measure, a column per size."""
    names = list(sizes)
    rows = [("First audio after you stop (median)", "first_audio_ms", "ms"), ("First audio (90th percentile)", "first_audio_p90_ms", "ms"),
            ("Speech made", "speed", "x"), ("Memory (process + GPU)", "memory_bytes", "gb"), ("Load time", "load_s", "s"),
            ("Your words written down wrong (WER)", "heard_wer", "pct"), ("Its speech heard wrong by Whisper (WER)", "spoken_wer", "pct"),
            ("Answers with the expected fact", "right", "of"), ("Turns that failed", "failed", "")]
    out = ["| | " + " | ".join(sizes[n].get("label", n) for n in names) + " |", "| --- |" + " --- |" * len(names)]
    for label, key, kind in rows:
        cells = [(f"{sizes[n][key]:.1f} s" if kind == "s" and sizes[n].get(key) is not None else fmt(sizes[n].get(key), kind)) for n in names]
        out.append(f"| {label} | " + " | ".join(cells) + " |")
    return "\n".join(out)
