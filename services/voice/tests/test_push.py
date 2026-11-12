"""Plan voice-mute 2.1: push to talk. Heard only while held; letting go sends the turn at once."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from helpers import chunks, quiet, tone, until
from test_agent_turns import FakeHub
from test_mute import answered, make

START = {"type": "start", "thread": "t_1", "pause_ms": 300, "talk": "push"}


@pytest.fixture
def hub():
    return FakeHub()


@pytest.fixture(params=["agent", "speech"])
def client(request, settings, tmp_path, hub, monkeypatch):
    with TestClient(make(settings, tmp_path, hub, monkeypatch, request.param)) as c:
        c.answers = request.param
        yield c


def send(ws, pcm):
    for c in chunks(pcm):
        ws.send_bytes(c)


def test_outside_a_press_nothing_starts_a_turn_and_a_press_is_sent_when_let_go(client, hub):
    with client.websocket_connect("/v1/realtime") as ws:
        ws.send_json({**START, "pause_ms": 5000})          # the pause would never end it: letting go does
        ready, _, _ = until(ws, "ready")
        assert ready["talk"] == "push"
        until(ws, "listening")
        send(ws, tone(0.8) + quiet(0.5))                    # loud, but not held
        ws.send_json({"type": "talk", "on": True})
        send(ws, tone(0.5))
        until(ws, "hearing")
        ws.send_json({"type": "talk", "on": False})
        heard, seen, _ = until(ws, "heard")
        assert "thinking" in [e["type"] for e in seen]
        assert answered(ws)["user"] == heard["text"]
        ws.send_json({"type": "stop"})
    if client.answers == "agent":
        assert hub.asked == [heard["text"]]


def test_a_tap_sends_nothing(client, hub):
    with client.websocket_connect("/v1/realtime") as ws:
        ws.send_json(START)
        until(ws, "listening")
        ws.send_json({"type": "talk", "on": True})
        send(ws, tone(0.1))
        until(ws, "hearing")
        ws.send_json({"type": "talk", "on": False})
        _, seen, _ = until(ws, "listening")
        assert "thinking" not in [e["type"] for e in seen]
        ws.send_json({"type": "text", "text": "typed"})       # the next thing it does is the typed turn
        assert until(ws, "heard")[0]["text"] == "typed"
        ws.send_json({"type": "stop"})
    if client.answers == "agent":
        assert hub.asked == ["typed"]


def test_a_press_during_a_reply_stops_it_and_hears_you(client, hub, monkeypatch):
    monkeypatch.setenv("FAKE_LLAMA_CHUNKS", "40")
    monkeypatch.setenv("FAKE_LLAMA_DELAY", "0.05")
    hub.steps = [{"state": "running", "text": "A long answer that keeps going and going for a good while.", "seq": 8}]
    with client.websocket_connect("/v1/realtime") as ws:
        ws.send_json(START)
        until(ws, "listening")
        ws.send_json({"type": "text", "text": "Tell me a story"})
        until(ws, "speaking")
        send(ws, tone(0.6))                                  # noise while it speaks: nothing
        ws.send_json({"type": "talk", "on": True, "played_ms": 200})
        turn, _, _ = until(ws, "turn")
        assert turn["interrupted"] is True
        send(ws, tone(0.5))
        until(ws, "hearing")
        ws.send_json({"type": "talk", "on": False})
        until(ws, "thinking")
        ws.send_json({"type": "stop"})
    if client.answers == "agent":
        assert hub.stops == 1 and len(hub.asked) == 2


def test_open_is_the_default_and_talk_is_ignored_there(client):
    with client.websocket_connect("/v1/realtime") as ws:
        ws.send_json({**START, "talk": None})
        ready, _, _ = until(ws, "ready")
        assert ready["talk"] == "open"
        ws.send_json({"type": "talk", "on": True})
        ws.send_json({"type": "mute", "on": True})            # the next answer is the mute's: talk did nothing
        _, seen, _ = until(ws, "muted")
        assert [e["type"] for e in seen] == ["listening"]
        ws.send_json({"type": "stop"})
