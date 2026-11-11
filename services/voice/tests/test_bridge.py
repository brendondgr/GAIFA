"""The bridge against the fake llama-server's scripted /v1/realtime."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from helpers import say, until
from voice.bridge import heard_part, instructions, transcript

START = {"type": "start", "pause_ms": 300}


@pytest.fixture
def client(settings, tmp_path):
    from voice.server import create_app

    with TestClient(create_app(settings, log_dir=tmp_path / "logs")) as c:
        yield c


def test_a_turn_end_to_end(client):
    with client.websocket_connect("/v1/realtime") as ws:
        ws.send_json(START)
        ready, _, _ = until(ws, "ready")
        assert ready["sample_rate_out"] == 24000 and ready["voice"] == "female" and ready["vad"] == "energy"
        until(ws, "listening")
        say(ws)
        until(ws, "hearing")
        until(ws, "thinking")
        final = None
        total = 0
        events = []
        while final is None:
            ev, seen, n = until(ws, "said")
            events += seen
            total += n
            final = ev if ev["final"] else None
        assert final["text"] == "Paris is the capital of France." and final["audio_ms"] == 1000
        ws.send_json({"type": "played"})
        turn, seen, n = until(ws, "turn")
        assert total + n == 24000 * 2                      # one second of reply audio reached the page
        assert turn["assistant"] == "Paris is the capital of France." and turn["user"].startswith("heard ")
        assert turn["interrupted"] is False and turn["saved"] is False and turn["first_audio_ms"] is not None
        assert any(e["type"] == "heard" for e in events + seen)
        until(ws, "listening")
        st = client.get("/v1/status").json()
        assert st["sessions"] == 1 and st["busy"] is True and st["stats"][0]["value"] == 1
        ws.send_json({"type": "stop"})
        until(ws, "done")
    assert client.get("/v1/status").json()["sessions"] == 0


def test_interrupting_a_reply(client, monkeypatch):
    monkeypatch.setenv("FAKE_LLAMA_DELAY", "0.1")
    monkeypatch.setenv("FAKE_LLAMA_CHUNKS", "30")
    monkeypatch.setenv("FAKE_LLAMA_REPLY", " ".join(f"w{i}" for i in range(30)))
    with client.websocket_connect("/v1/realtime") as ws:
        ws.send_json(START)
        until(ws, "listening")
        say(ws)
        until(ws, "speaking")
        say(ws, 0.3, 0.0)                                   # you talk over it: held, not sent on yet
        ws.send_json({"type": "interrupt", "played_ms": 200})
        turn, _, _ = until(ws, "turn")
        assert turn["interrupted"] is True and turn["assistant"].endswith("…")
        assert 1 <= len(turn["assistant"].split()) < 30
        until(ws, "hearing")                               # the held audio starts your next turn
        say(ws, 0.2, 0.7)
        until(ws, "thinking")
        ev, _, _ = until(ws, "said")
        assert ev["text"].startswith("w0")                 # a fresh reply, none of the cancelled one's events
        ws.send_json({"type": "stop"})


def test_a_typed_turn(client):
    with client.websocket_connect("/v1/realtime") as ws:
        ws.send_json({**START, "voice": "male", "language": "de"})
        assert until(ws, "ready")[0]["voice"] == "male"
        until(ws, "listening")
        ws.send_json({"type": "text", "text": "What is the capital of France?"})
        assert until(ws, "heard")[0]["text"] == "What is the capital of France?"
        while not until(ws, "said")[0]["final"]:
            pass
        ws.send_json({"type": "played"})
        assert until(ws, "turn")[0]["user"] == "What is the capital of France?"


def test_one_conversation_at_a_time(client):
    with client.websocket_connect("/v1/realtime") as ws:
        ws.send_json(START)
        until(ws, "listening")
        with client.websocket_connect("/v1/realtime") as other:
            other.send_json(START)
            assert other.receive_json()["code"] == "busy"
            with pytest.raises(WebSocketDisconnect) as e:
                other.receive_json()
            assert e.value.code == 4409
        ws.send_json({"type": "stop"})


def test_a_bad_start(client):
    for first in ({"type": "hello"}, {"type": "start", "voice": "robot"}, {"type": "start", "pause_ms": 5}):
        with client.websocket_connect("/v1/realtime") as ws:
            ws.send_json(first)
            assert ws.receive_json()["code"] == "bad_start"
            with pytest.raises(WebSocketDisconnect) as e:
                ws.receive_json()
            assert e.value.code == 4400
    assert client.get("/v1/status").json()["sessions"] == 0


def test_the_engine_going_away(client, monkeypatch):
    monkeypatch.setenv("FAKE_LLAMA_MODE", "drop")
    with client.websocket_connect("/v1/realtime") as ws:
        ws.send_json(START)
        until(ws, "listening")
        say(ws)
        err, _, _ = until(ws, "error")
        assert err["code"] == "engine_failed"
        until(ws, "done")


def test_a_missing_model(client, settings):
    settings.mmproj_path.unlink()
    with client.websocket_connect("/v1/realtime") as ws:
        ws.send_json(START)
        err = ws.receive_json()
        assert err["code"] == "model_missing" and "gaifa setup voice" in err["fix"]


def test_what_you_heard_of_an_interrupted_reply():
    text = "one two three four five six seven eight nine ten"
    assert heard_part(text, 500, 1000) == "one two three four five…"
    assert heard_part(text, 0, 1000) == "" and heard_part(text, 2000, 1000) == text
    assert heard_part("one two", 500, 300, complete=False) == "one two…"


def test_instructions_carry_the_chat():
    ctx = {"instructions": "The user is Brendon.", "history": [{"role": "user", "text": "My dog is Biscuit."},
                                                               {"role": "assistant", "text": "Nice\nname."}]}
    text = instructions(ctx, [{"role": "user", "text": "And my cat is Pepper."}])
    assert text.startswith("Respond with interleaved text and audio.") and "The user is Brendon." in text
    assert text.endswith("User: My dog is Biscuit.\nAssistant: Nice name.\nUser: And my cat is Pepper.")
    long = [{"role": "user", "text": "x" * 300} for _ in range(200)]
    assert len(transcript(long)) <= 24000 and transcript(long).count("User:") < 200
