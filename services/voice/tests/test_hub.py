"""The chat's side of a conversation: its context opens the session, and each turn is written into it."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from helpers import until
from voice.hub import Hub, HubError


class FakeHub(Hub):
    def __init__(self) -> None:
        super().__init__("")
        self.turns: list[tuple[str, dict]] = []
        self.fail = False

    async def voice_context(self, thread):
        if thread == "t_gone":
            raise HubError(404, "no chat 't_gone'", "not_found")
        return {"instructions": "The user is Brendon.", "history": [{"role": "user", "text": "My dog is Biscuit."},
                                                                    {"role": "assistant", "text": "A lovely name."}]}

    async def voice_turn(self, thread, turn):
        if self.fail:
            return None
        self.turns.append((thread, turn))
        return {"user_seq": 1, "assistant_seq": 2}


@pytest.fixture
def hub():
    return FakeHub()


@pytest.fixture
def client(settings, tmp_path, hub, monkeypatch):
    from voice.server import create_app

    monkeypatch.setenv("FAKE_LLAMA_MODE", "log")
    with TestClient(create_app(settings, hub=hub, log_dir=tmp_path / "logs")) as c:
        c.log = tmp_path / "logs" / "llama-server.log"
        yield c


def talk(ws, text="What is my dog called?"):
    ws.send_json({"type": "text", "text": text})
    while not until(ws, "said")[0]["final"]:
        pass
    ws.send_json({"type": "played"})
    return until(ws, "turn")[0]


def test_the_chat_opens_the_session_and_gets_the_turns(client, hub):
    with client.websocket_connect("/v1/realtime") as ws:
        ws.send_json({"type": "start", "thread": "t_1", "voice": "male", "language": "en-GB"})
        until(ws, "listening")
        turn = talk(ws)
        assert turn["saved"] is True
        assert hub.turns == [("t_1", {"user": "What is my dog called?", "assistant": "Paris is the capital of France.",
                                      "model": "voice/lfm3-omni-2b", "first_audio_ms": turn["first_audio_ms"],
                                      "interrupted": False})]
        hub.fail = True                                     # the chat can't be written: the talk goes on
        assert talk(ws, "Again?")["saved"] is False
        ws.send_json({"type": "stop"})
        until(ws, "done")
    sessions = [json.loads(line[8:]) for line in client.log.read_text().splitlines() if line.startswith("SESSION ")]
    conv = next(s for s in sessions if s["type"] == "realtime")
    assert conv["instructions"].startswith("Respond with interleaved text and audio.")
    assert "The user is Brendon." in conv["instructions"]
    assert conv["instructions"].endswith("User: My dog is Biscuit.\nAssistant: A lovely name.")
    assert conv["audio"]["output"]["voice"] == "male" and conv["audio"]["output"]["language"] == "en"
    assert conv["output_modalities"] == ["text", "audio"] and conv["audio"]["input"]["format"]["rate"] == 16000
    asr = next(s for s in sessions if s["type"] == "transcription")
    assert asr["audio"]["input"]["transcription"] == {"language": "en"}


def test_nothing_is_written_without_a_chat_or_when_told_not_to(client, hub):
    for start in ({"type": "start"}, {"type": "start", "thread": "t_1", "save": False}):
        with client.websocket_connect("/v1/realtime") as ws:
            ws.send_json(start)
            until(ws, "listening")
            assert talk(ws)["saved"] is False
            ws.send_json({"type": "stop"})
    assert hub.turns == []


def test_a_chat_that_does_not_exist(client):
    with client.websocket_connect("/v1/realtime") as ws:
        ws.send_json({"type": "start", "thread": "t_gone"})
        assert ws.receive_json()["code"] == "not_found"
