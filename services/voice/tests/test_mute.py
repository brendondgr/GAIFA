"""Plan voice-mute 1.1: muted, nothing the microphone picks up starts a turn or talks over the reply."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from helpers import chunks, quiet, say, tone, until
from test_agent_turns import FakeHub

START = {"type": "start", "thread": "t_1", "pause_ms": 300}


@pytest.fixture
def hub():
    return FakeHub()


def make(settings, tmp_path, hub, monkeypatch, answers):
    from voice.server import create_app

    monkeypatch.setenv("FAKE_LLAMA_MODE", "log")
    app = create_app(settings, hub=hub, log_dir=tmp_path / "logs")
    app.state.voice_mode = {"answers": answers}
    return app


@pytest.fixture(params=["agent", "speech"])
def client(request, settings, tmp_path, hub, monkeypatch):
    with TestClient(make(settings, tmp_path, hub, monkeypatch, request.param)) as c:
        c.answers = request.param
        c.log = tmp_path / "logs" / "llama-server.log"
        yield c


def answered(ws) -> dict:
    """Read the reply to its end, say it played, and return the turn."""
    while not until(ws, "said")[0]["final"]:
        pass
    ws.send_json({"type": "played"})
    return until(ws, "turn")[0]


def logged(client, prefix):
    return [line[len(prefix):] for line in client.log.read_text().splitlines() if line.startswith(prefix)]


def test_while_muted_speech_starts_no_turn_and_unmuting_hears_again(client, hub):
    with client.websocket_connect("/v1/realtime") as ws:
        ws.send_json({**START, "muted": True})
        ready, _, _ = until(ws, "ready")
        assert ready["muted"] is True
        until(ws, "listening")
        say(ws)
        ws.send_json({"type": "mute", "on": False})          # the next event is the answer to this, not a turn
        ev, seen, _ = until(ws, "muted")
        assert ev["on"] is False and [e["type"] for e in seen] == []
        say(ws)
        until(ws, "heard")
        answered(ws)
        ws.send_json({"type": "stop"})
    if client.answers == "agent":
        assert len(hub.asked) == 1


def test_muting_in_the_middle_of_a_sentence_sends_nothing(client, hub):
    with client.websocket_connect("/v1/realtime") as ws:
        ws.send_json(START)
        until(ws, "listening")
        for c in chunks(tone(0.6)):                           # talking, no pause yet
            ws.send_bytes(c)
        until(ws, "hearing")
        ws.send_json({"type": "mute", "on": True})
        ev, seen, _ = until(ws, "muted")
        assert ev["on"] is True and "listening" in [e["type"] for e in seen]
        for c in chunks(quiet(0.7) + tone(0.6) + quiet(0.7)):  # the pause, then more: none of it is heard
            ws.send_bytes(c)
        ws.send_json({"type": "text", "text": "typed still works"})
        heard, seen, _ = until(ws, "heard")
        assert heard["text"] == "typed still works" and "hearing" not in [e["type"] for e in seen]
        ws.send_json({"type": "stop"})
    assert "transcription" in logged(client, "CLEAR ")
    if client.answers == "agent":
        assert hub.asked == ["typed still works"]


def test_a_reply_goes_on_through_a_mute_and_talking_over_it_does_nothing(client, hub, monkeypatch):
    monkeypatch.setenv("FAKE_LLAMA_CHUNKS", "12")
    monkeypatch.setenv("FAKE_LLAMA_DELAY", "0.03")
    hub.steps = [{"state": "done", "text": "A long answer that keeps going for a while.", "seq": 9}]
    with client.websocket_connect("/v1/realtime") as ws:
        ws.send_json(START)
        until(ws, "listening")
        ws.send_json({"type": "text", "text": "Tell me something"})
        until(ws, "speaking")
        ws.send_json({"type": "mute", "on": True})
        ws.send_json({"type": "interrupt", "played_ms": 100})  # an out-of-date page: ignored
        for c in chunks(tone(0.5)):
            ws.send_bytes(c)
        final = None
        while final is None:
            ev, seen, _ = until(ws, "said")
            assert "turn" not in [e["type"] for e in seen]
            final = ev if ev["final"] else None
        ws.send_json({"type": "played"})
        turn, _, _ = until(ws, "turn")
        assert turn["interrupted"] is False and turn["assistant"]
        ws.send_json({"type": "stop"})
    assert hub.stops == 0


def test_mute_and_unmute_are_answered(client):
    with client.websocket_connect("/v1/realtime") as ws:
        ws.send_json(START)
        ready, _, _ = until(ws, "ready")
        assert ready["muted"] is False
        for on in (True, True, False):
            ws.send_json({"type": "mute", "on": on})
            assert until(ws, "muted")[0]["on"] is on
        ws.send_json({"type": "stop"})
