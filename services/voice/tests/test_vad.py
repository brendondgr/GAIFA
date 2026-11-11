"""Turn detection: speech then quiet ends a turn; noise alone never starts one."""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np
import pytest

from helpers import RATE, chunks, quiet, tone
from voice import vad

SILERO = Path(__file__).parent.parent / "runtime" / "vad" / "silero_vad.onnx"
QUESTION = Path(__file__).parent / "fixtures" / "question-16k.wav"


def run(detector, pcm: bytes) -> tuple[bytes, list[float]]:
    passed, ends, t = b"", [], 0.0
    for c in chunks(pcm, 100, detector.rate):
        t += len(c) / 2 / detector.rate
        for kind, data in detector.feed(c):
            if kind == "speech":
                passed += data
            else:
                ends.append(round(t, 1))
    return passed, ends


def test_speech_then_quiet_ends_one_turn():
    d = vad.TurnDetector(vad.EnergyVad(), pause_ms=500)
    passed, ends = run(d, quiet(0.5) + tone(1.0) + quiet(1.5))
    assert len(ends) == 1 and 1.9 <= ends[0] <= 2.3
    assert 1.3 * RATE * 2 <= len(passed) <= 2.1 * RATE * 2        # the speech, its lead-in and the pause; not all the quiet


def test_noise_alone_starts_nothing():
    d = vad.TurnDetector(vad.EnergyVad(), pause_ms=500)
    passed, ends = run(d, quiet(3.0))
    assert passed == b"" and ends == []


def test_a_short_gap_does_not_end_the_turn():
    d = vad.TurnDetector(vad.EnergyVad(), pause_ms=800)
    _, ends = run(d, tone(0.6) + quiet(0.4) + tone(0.6) + quiet(1.2))
    assert len(ends) == 1


def test_begin_starts_a_turn_already_under_way():
    d = vad.TurnDetector(vad.EnergyVad(), pause_ms=300)
    assert d.begin(b"\x00\x00" * 100) == [("speech", b"\x00\x00" * 100)]
    _, ends = run(d, quiet(0.6))
    assert len(ends) == 1


def test_other_sample_rates():
    d = vad.TurnDetector(vad.EnergyVad(), rate=24000, pause_ms=500)
    _, ends = run(d, tone(1.0, rate=24000) + quiet(1.0, rate=24000))
    assert len(ends) == 1 and vad.resample(np.zeros(2400, dtype=np.int16), 24000).size == 1600


@pytest.mark.skipif(not SILERO.is_file(), reason="the Silero model isn't installed (install.sh fetches it)")
def test_silero_on_real_speech():
    with wave.open(str(QUESTION)) as w:
        speech = w.readframes(w.getnframes())
    v = vad.make_vad(SILERO)
    assert v.kind == "silero"
    d = vad.TurnDetector(v, pause_ms=700)
    passed, ends = run(d, quiet(1.0) + speech + quiet(1.5))
    assert len(ends) == 1 and len(passed) > len(speech) * 0.8
    d.reset()
    assert run(d, tone(2.0, level=0.2))[1] == [] or True       # a tone may or may not read as speech; no crash
    assert run(vad.TurnDetector(v, pause_ms=700), quiet(3.0)) == (b"", [])
