"""The size comparison's scoring and report, on fixtures (no model)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evals import compare, score


def test_word_error_rate():
    assert score.wer("What is the capital of France?", "what is the capital of france") == 0
    assert score.wer("My favourite number is forty two.", "My favorite number is 42.") == 0     # spelling and digits aren't errors
    assert score.wer("one two three four", "one three four") == 0.25
    assert score.wer("hello there", "") == 1.0 and score.wer("", "") == 0.0 and score.wer("", "extra") == 1.0
    assert score.wer("¿Cuántos días tiene una semana?", "cuantos dias tiene una semana") == 0
    assert score.words("It costs 1,200 dollars — that's all") == ["it", "costs", "1200", "dollars", "that's", "all"]


def test_expected_facts():
    assert score.has_all("The capital of France is Paris.", ["Paris"])
    assert score.has_all("That comes to forty-two.", ["42|forty two"]) and score.has_all("It is 42.", ["42|forty two"])
    assert not score.has_all("I am not sure.", ["Paris"])
    assert score.has_all("Dr. Nowak and Prof. Tanaka", ["Nowak", "Tanaka"]) and not score.has_all("Dr. Nowak", ["Nowak", "Tanaka"])


def rows(ms):
    return [{"n": 1, "id": "s1", "kind": "short", "text": "What is the capital of France?", "heard": "What is the capital of France?",
             "said": "Paris.", "first_audio_ms": ms, "audio_ms": 2000, "reply_s": 0.5, "heard_wer": 0.0, "spoken_wer": 0.0, "right": True},
            {"n": 2, "id": "n1", "kind": "numbers", "text": "What is seventeen plus twenty five?", "heard": "What is seventeen plus twenty?",
             "said": "Thirty seven.", "first_audio_ms": ms + 40, "audio_ms": 1000, "reply_s": 0.25, "heard_wer": 1 / 6, "spoken_wer": 0.5,
             "right": False},
            {"n": 3, "id": "l1", "kind": "long", "text": "A long question", "error": "timed out"}]


def test_summary_and_table():
    s = score.summary(rows(100))
    assert s["turns"] == 3 and s["failed"] == 1 and s["first_audio_ms"] in (100, 140) and s["first_audio_p90_ms"] == 140
    assert s["speed"] == 0.25 and s["right"] == (1, 2) and abs(s["heard_wer"] - 1 / 12) < 1e-9 and s["spoken_wer"] == 0.25
    assert score.summary([])["first_audio_ms"] is None and score.summary([])["right"] is None
    sizes = {"q4_k_m": {"label": "Q4_K_M", **s, "load_s": 1.04, "memory_bytes": 3.2e9},
             "q8_0": {"label": "Q8_0", **score.summary(rows(130)), "load_s": 1.3, "memory_bytes": 4.0e9}}
    t = score.table(sizes)
    assert "| | Q4_K_M | Q8_0 |" in t and "| Speech made | 4.0× real time | 4.0× real time |" in t
    assert "| Memory (process + GPU) | 3.2 GB | 4.0 GB |" in t and "| Answers with the expected fact | 1 of 2 | 1 of 2 |" in t
    assert "| Turns that failed | 1 | 1 |" in t and "| Load time | 1.0 s | 1.3 s |" in t


def test_the_report_and_conversations(tmp_path):
    sizes = {"q4_k_m": {"label": "Q4_K_M", **score.summary(rows(100)), "load_s": 1.0, "memory_bytes": 3.2e9, "rows": rows(100)},
             "q8_0": {"label": "Q8_0", **score.summary(rows(130)), "load_s": 1.3, "memory_bytes": 4.0e9, "rows": rows(130)}}
    text = compare.report(sizes, argparse.Namespace(audio="outputs/voice/eval"), "2026-11-11")
    assert text.startswith("# Voice mode's speech model: Q4_K_M against Q8_0") and "## Every turn" in text
    assert "- Q4_K_M (100 ms) ✓: Paris." in text and "- Q8_0: failed: timed out" in text
    assert "*(heard as: What is seventeen plus twenty?)*" in text and "| Short questions |" in text and "| Tools |" not in text
    prompts = json.loads((Path(compare.HERE) / "prompts.json").read_text())["prompts"]
    assert len(prompts) == 32 and len({p["id"] for p in prompts}) == 32
    convs = compare.conversations(prompts, tools=False)
    assert [p["id"] for p in next(c for c in convs if c[0]["id"] == "f1a")] == ["f1a", "f1b"]
    assert sum(len(c) for c in convs) == 27 and sum(len(c) for c in compare.conversations(prompts, tools=True)) == 32
    assert all(p.get("tool") for p in prompts if p["kind"] == "tool")
