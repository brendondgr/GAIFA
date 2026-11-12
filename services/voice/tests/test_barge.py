"""Plan voice-mute 3.2–3.3: talking over the reply is decided by the mod, by speech; a false one gives the answer back."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from helpers import chunks, quiet, tone, until
from test_agent_turns import FakeHub
from test_mute import make
from voice import vad
from voice.agent_turns import heard_upto, is_filler, resume_point

START = {"type": "start", "thread": "t_1", "pause_ms": 300}
SILERO = Path(__file__).parent.parent / "runtime" / "vad" / "silero_vad.onnx"
NOISE = Path(__file__).parent.parent / "evals" / "noise"
LONG = "First sentence of the answer. Second sentence goes on for a while. Third sentence ends it here."


@pytest.fixture
def hub():
    return FakeHub()


def client_for(settings, tmp_path, hub, monkeypatch, answers="agent", **vm):
    monkeypatch.setenv("FAKE_LLAMA_CHUNKS", "40")
    monkeypatch.setenv("FAKE_LLAMA_DELAY", "0.05")
    app = make(settings, tmp_path, hub, monkeypatch, answers)
    app.state.voice_mode.update(vm)
    c = TestClient(app)
    c.log = tmp_path / "logs" / "llama-server.log"
    return c


def tts(c):
    return [json.loads(x[4:])["input"] for x in c.log.read_text().splitlines() if x.startswith("TTS ")]


def send(ws, pcm):
    for c in chunks(pcm):
        ws.send_bytes(c)


def interrupt_it(ws, played_ms=2200):
    """A voice over the reply: the mod says so, the page answers how far it played."""
    until(ws, "speaking")
    send(ws, tone(0.5))
    until(ws, "interrupted")
    ws.send_json({"type": "interrupt", "played_ms": played_ms})


def test_a_noise_that_held_no_words_gives_the_answer_back(settings, tmp_path, hub, monkeypatch):
    monkeypatch.setenv("FAKE_LLAMA_HEARD", "Hmm.")
    hub.steps = [{"state": "running", "text": LONG, "seq": 8}, {"state": "done", "text": "", "seq": 8}]
    with client_for(settings, tmp_path, hub, monkeypatch) as c, c.websocket_connect("/v1/realtime") as ws:
        ws.send_json(START)
        ready, _, _ = until(ws, "ready")
        assert ready["interrupt"] == "speech"
        until(ws, "listening")
        ws.send_json({"type": "text", "text": "Tell me something"})
        interrupt_it(ws, played_ms=99999)                    # it had played to the end of what it had sent
        send(ws, quiet(0.6))                                  # the cough is over: its words are none
        _, seen, _ = until(ws, "resumed")
        assert "turn" not in [e["type"] for e in seen]       # paused, not ended
        final = None
        while final is None:
            ev, _, _ = until(ws, "said")
            final = ev if ev["final"] else None
        ws.send_json({"type": "played"})
        turn, _, _ = until(ws, "turn")
        assert turn["interrupted"] is False and turn["user"] == "Tell me something"
        ws.send_json({"type": "stop"})
    assert hub.stops == 0 and hub.asked == ["Tell me something"]
    said = tts(c)
    assert said[0] == LONG and said[1] in LONG and len(said) == 2 and said[1].endswith("ends it here.")


def test_words_over_it_end_that_turn_and_are_the_next_message(settings, tmp_path, hub, monkeypatch):
    monkeypatch.setenv("FAKE_LLAMA_HEARD", "No, check my calendar instead")
    hub.steps = [{"state": "running", "text": LONG, "seq": 8}]
    with client_for(settings, tmp_path, hub, monkeypatch) as c, c.websocket_connect("/v1/realtime") as ws:
        ws.send_json(START)
        until(ws, "listening")
        ws.send_json({"type": "text", "text": "Tell me something"})
        interrupt_it(ws)
        send(ws, quiet(0.6))
        turn, _, _ = until(ws, "turn")
        assert turn["interrupted"] is True and turn["user"] == "Tell me something"
        assert turn["assistant"] == "First sentence of the answer."          # as far as it got, to the sentence
        assert until(ws, "turn")[0]["user"] == "No, check my calendar instead"
        ws.send_json({"type": "stop"})
    assert hub.stops == 1 and hub.asked == ["Tell me something", "No, check my calendar instead"]


def test_interrupt_off_lets_nothing_stop_it(settings, tmp_path, hub, monkeypatch):
    hub.steps = [{"state": "done", "text": "A short answer.", "seq": 9}]
    with client_for(settings, tmp_path, hub, monkeypatch, interrupt="off") as c, c.websocket_connect("/v1/realtime") as ws:
        ws.send_json(START)
        ready, _, _ = until(ws, "ready")
        assert ready["interrupt"] == "off"
        ws.send_json({"type": "text", "text": "Hello"})
        until(ws, "speaking")
        send(ws, tone(0.5))
        ws.send_json({"type": "interrupt", "played_ms": 100})   # an out-of-date page: ignored
        final = None
        while final is None:
            ev, seen, _ = until(ws, "said")
            assert not {"interrupted", "turn"} & {e["type"] for e in seen}
            final = ev if ev["final"] else None
        ws.send_json({"type": "played"})
        assert until(ws, "turn")[0]["interrupted"] is False
        ws.send_json({"type": "stop"})


def test_the_speech_model_by_itself_is_interrupted_by_the_mod_too(settings, tmp_path, hub, monkeypatch):
    with client_for(settings, tmp_path, hub, monkeypatch, answers="speech") as c, c.websocket_connect("/v1/realtime") as ws:
        ws.send_json(START)
        until(ws, "listening")
        ws.send_json({"type": "text", "text": "Hello"})
        interrupt_it(ws, played_ms=200)
        assert until(ws, "turn")[0]["interrupted"] is True
        ws.send_json({"type": "stop"})


def test_where_a_paused_answer_goes_on_and_what_counts_as_no_words():
    text = "One two three. Four five six! Seven eight nine? Ten."
    assert resume_point(text, 0) == 0
    assert text[resume_point(text, 20):].startswith("Four five six!")
    assert text[resume_point(text, 40):].startswith("Seven")
    assert resume_point(text, 5) == 0                           # still in the first sentence: from the start
    marks = [(0, 29, 0), (30, 22, 1000)]                         # two chunks; the second's audio began at byte 1000
    assert heard_upto(marks, 1500, 500, 1.0) == 14               # half of the first
    assert heard_upto(marks, 2000, 1500, 1.0, done=True) == 30 + 11   # half of the second, whose audio is all there
    assert heard_upto(marks, 1100, 1050, 1.0) == 30 + int(22 * 50 / (22 * 70))   # the second still coming: by its length
    assert all(is_filler(w) for w in ("", "Hmm.", "uh", "Mm-hm", "Thank you.", "you", "Mem.", "Bye."))
    assert not any(is_filler(w) for w in ("Stop.", "Wait", "No.", "What?", "No, the other one", "What time is it?", "Hold on"))


@pytest.mark.skipif(not SILERO.is_file() or not (NOISE / "stop.wav").is_file(), reason="needs Silero and the eval's clips")
def test_silero_tells_a_voice_from_noise():
    from evals.noise import RATE, db, read_wav, synth

    rng = np.random.default_rng(3)
    def fires(x):
        b = vad.BargeDetector(vad.make_vad(SILERO))
        y = np.concatenate([np.zeros(RATE // 2, np.float32), x, np.zeros(RATE // 2, np.float32)])
        pcm = (np.clip(y, -1, 1) * 32767).astype(np.int16).tobytes()
        return any(b.feed(pcm[i:i + 3200]) for i in range(0, len(pcm), 3200))
    for name, x in synth(rng).items():
        assert not fires(db(x, -20)), name
    for name in ("stop", "wait", "hold-on", "no"):
        assert fires(db(read_wav((NOISE / f"{name}.wav").read_bytes()), -24)), name
