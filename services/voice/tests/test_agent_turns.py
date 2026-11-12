"""Plan voice-speech-model 6.2: voice mode through the chat's agent. The speech model hears and speaks; the chat answers."""

from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from helpers import say, until
from voice.hub import Hub, HubError
from voice.numbers import spoken_numbers
from voice.speak import chunks, speakable

START = {"type": "start", "thread": "t_1", "pause_ms": 300}


class FakeHub(Hub):
    """The agent's side: a chat whose turn says `steps` one after another."""

    def __init__(self) -> None:
        super().__init__("")
        self.asked: list[str] = []
        self.steps: list[dict] = [{"state": "done", "text": "You have the **dentist** at ten.", "seq": 9}]
        self.turns: list[dict] = []
        self.contexts = self.stops = 0
        self.busy = False
        self.gap = 0.0

    async def voice_context(self, thread):
        self.contexts += 1
        return {}

    async def voice_turn(self, thread, turn):
        self.turns.append(turn)
        return {"user_seq": 1}

    async def voice_ask(self, thread, text):
        if self.busy:
            raise HubError(409, "the chat's own turn is running", "ask_failed")
        self.asked.append(text)
        return {"seq": 7}

    async def voice_step(self, thread, after, wait=25):
        await asyncio.sleep(self.gap)
        return self.steps.pop(0) if self.steps else {"state": "done", "text": "", "seq": after}

    async def voice_stop(self, thread):
        self.stops += 1


@pytest.fixture
def hub():
    return FakeHub()


@pytest.fixture
def client(settings, tmp_path, hub, monkeypatch):
    from voice.server import create_app

    monkeypatch.setenv("FAKE_LLAMA_MODE", "log")
    app = create_app(settings, hub=hub, log_dir=tmp_path / "logs")
    app.state.voice_mode = {"answers": "agent", "tools": ["time_now"], "ask_chat": True}     # [voice_mode], without a hub
    with TestClient(app) as c:
        c.log = tmp_path / "logs" / "llama-server.log"
        yield c


def lines(client, prefix):
    return [json.loads(line[len(prefix):]) for line in client.log.read_text().splitlines() if line.startswith(prefix)]


def test_a_spoken_turn_goes_to_the_chat_and_its_answer_is_spoken(client, hub):
    hub.steps = [{"state": "running", "text": "Let me look at your calendar.", "seq": 8},
                 {"state": "waiting", "text": "", "seq": 8},                     # a card is on screen: it waits
                 {"state": "done", "text": "You have the **dentist** at ten.\n\n- and `lunch` at noon", "seq": 11}]
    with client.websocket_connect("/v1/realtime") as ws:
        ws.send_json(START)
        ready, _, _ = until(ws, "ready")
        assert ready["answers"] == "agent"
        until(ws, "listening")
        say(ws)
        heard, seen, _ = until(ws, "heard")
        assert "thinking" in [e["type"] for e in seen]
        final, audio, seen = None, 0, []
        while final is None:
            ev, before, n = until(ws, "said")
            audio, seen = audio + n, seen + before
            final = ev if ev["final"] else None
        assert "speaking" in [e["type"] for e in seen] and audio > 0
        assert final["text"] == "Let me look at your calendar. You have the dentist at ten. and lunch at noon" and final["audio_ms"] > 0
        ws.send_json({"type": "played"})
        turn, _, _ = until(ws, "turn")
        assert turn["saved"] is True and turn["answers"] == "agent" and turn["user"] == heard["text"] and not turn["interrupted"]
        until(ws, "listening")
        ws.send_json({"type": "stop"})
    assert hub.asked == [heard["text"]]                       # your words, as a message of the chat
    assert hub.turns == [] and hub.contexts == 0              # the chat holds the turn; no speech-model context or tools
    assert [s for s in lines(client, "SESSION ") if s.get("type") == "realtime"] == []     # no conversation session: only the ears
    said = [t["input"] for t in lines(client, "TTS ")]
    assert said == ["Let me look at your calendar.", "You have the dentist at ten. and lunch at noon"]
    assert lines(client, "TTS ")[0]["voice"] == "female" and lines(client, "TTS ")[0]["stream"] is True


def test_talking_over_it_stops_the_speech_and_the_running_turn(client, hub, monkeypatch):
    monkeypatch.setenv("FAKE_LLAMA_CHUNKS", "40")
    monkeypatch.setenv("FAKE_LLAMA_DELAY", "0.05")
    hub.steps = [{"state": "running", "text": "First I will read the whole folder, which takes a while.", "seq": 8}]
    with client.websocket_connect("/v1/realtime") as ws:
        ws.send_json(START)
        until(ws, "listening")
        ws.send_json({"type": "text", "text": "Tidy up my notes folder"})
        until(ws, "speaking")
        ws.send_json({"type": "interrupt", "played_ms": 300})
        until(ws, "listening")                                 # paused, hearing what interrupted (voice-mute 3.3)
        ws.send_json({"type": "text", "text": "Never mind"})   # words: that turn ends, and this is the next
        turn, _, _ = until(ws, "turn")
        assert turn["interrupted"] is True and turn["user"] == "Tidy up my notes folder"
        until(ws, "turn")
        ws.send_json({"type": "stop"})
    assert hub.stops == 1 and hub.asked[0] == "Tidy up my notes folder"


def test_a_busy_chat_is_said_not_sent(client, hub):
    hub.busy = True
    with client.websocket_connect("/v1/realtime") as ws:
        ws.send_json(START)
        until(ws, "listening")
        ws.send_json({"type": "text", "text": "Hello"})
        err, _, _ = until(ws, "error")
        assert err["code"] == "turn_running"
        until(ws, "listening")
        ws.send_json({"type": "stop"})
    assert hub.asked == []


def test_the_start_can_ask_for_the_speech_model_itself(client, hub):
    """`answers: "speech"` (the bar's switch) wins over the setting; without a chat it is always the speech model."""
    for start in ({**START, "answers": "speech"}, {"type": "start", "pause_ms": 300}):
        with client.websocket_connect("/v1/realtime") as ws:
            ws.send_json(start)
            ready, _, _ = until(ws, "ready")
            assert ready["answers"] == "speech"
            ws.send_json({"type": "stop"})
    assert hub.contexts == 1 and hub.asked == []


def test_an_answer_as_words():
    md = "<think>hm</think>## Plan\n\n1. Read `a.py`\n\n```py\nprint(1)\n```\n\nSee [the docs](https://x.test/a) or https://y.test.\n\n| a | b |\n"
    assert speakable(md) == "Plan\n\n1. Read a.py\n\n(a code block)\n\nSee the docs or"
    assert speakable("**~104.8 GB** free — plenty → go") == "about 104.8 GB free, plenty to go"
    assert speakable(None) == "" and len(speakable("word. " * 2000)) <= 4000
    parts = chunks("One. Two! " + "long " * 150 + "end. Three?", size=100)
    assert parts[0] == "One. Two!" and all(len(p) <= 100 for p in parts) and parts[-1].endswith("Three?")
    assert " ".join(parts).split() == ("One. Two! " + "long " * 150 + "end. Three?").split()


def test_numbers_are_said_as_words():
    said = spoken_numbers("About 105 GB of 130 is free, roughly 3.4GB held. Your call is at 3:30 p.m. (or 9:05, or 14:00) on "
                          "November 12, 2026; 45% done, $1,250.50 spent, the 21st and 3rd try, 1,024 files, 2005, 1900, 007.")
    assert said == ("About one hundred five GB of one hundred thirty is free, roughly three point four GB held. Your call is at "
                    "three thirty p.m. (or nine oh five, or fourteen) on November twelve, twenty twenty-six; forty-five percent "
                    "done, one thousand two hundred fifty point five zero dollars spent, the twenty-first and third try, "
                    "one thousand twenty-four files, two thousand five, nineteen hundred, zero zero seven.")
    assert spoken_numbers("llama.cpp b12292, v1.2.3 and 127.0.0.1 stay") == "llama.cpp b12292, v1.2.3 and 127.0.0.1 stay"
    assert spoken_numbers("12,000,000 and 40") == "twelve million and forty"
