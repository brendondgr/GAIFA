"""Phase 5: tools in a voice conversation, through a fake hub, and handing a question to the chat's model."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from helpers import until
from voice import tools
from voice.hub import Hub, HubError


class FakeHub(Hub):
    def __init__(self) -> None:
        super().__init__("")
        self.calls: list[tuple] = []
        self.turns: list[dict] = []
        self.asked: list[str] = []
        self.status = "done"

    async def tool(self, name):
        if name == "nope":
            raise HubError(404, "no tool nope", "unknown_tool")
        return {"name": name, "description": "What's on the user's calendar. " + "x " * 400,
                "parameters": {"type": "object", "properties": {"day": {"type": "string"}}}}

    async def call_tool(self, name, arguments, thread, wait=25):
        self.calls.append((name, arguments, thread))
        if self.status == "denied":
            return {"status": "denied", "tool": name, "error": {"code": "unattended", "detail": f"{name}: it changes your calendar"}}
        return {"status": self.status, "tool": name, "result": {"events": [{"time": "10:00", "title": "Dentist"}]}}

    async def voice_context(self, thread):
        return {}

    async def voice_turn(self, thread, turn):
        self.turns.append(turn)
        return {"user_seq": 1}

    async def voice_ask(self, thread, text):
        self.asked.append(text)
        return {"seq": 7}

    async def voice_answer(self, thread, after, wait_s):
        return {"state": "done", "text": "Sales rose nine percent."}


@pytest.fixture
def hub():
    return FakeHub()


@pytest.fixture
def client(settings, tmp_path, hub, monkeypatch):
    from voice.server import create_app

    monkeypatch.setenv("FAKE_LLAMA_MODE", "log")
    app = create_app(settings, hub=hub, log_dir=tmp_path / "logs")
    with TestClient(app) as c:
        c.log = tmp_path / "logs" / "llama-server.log"
        c.app_ = app
        yield c


def talk(ws, text="What's on my calendar tomorrow?"):
    ws.send_json({"type": "text", "text": text})
    events = []
    while True:
        ev, seen, _ = until(ws, "said")
        events += seen
        if ev["final"]:
            break
    ws.send_json({"type": "played"})
    turn, seen, _ = until(ws, "turn")
    return turn, events + seen, ev


def lines(client, prefix):
    return [line[len(prefix):] for line in client.log.read_text().splitlines() if line.startswith(prefix)]


def test_a_tool_call_runs_through_the_hub(client, hub):
    client.app_.state.voice_mode = {"tools": ["calendar_agenda", "time_now", "nope"], "ask_chat": False}
    with client.websocket_connect("/v1/realtime") as ws:
        ws.send_json({"type": "start", "thread": "t_1"})
        until(ws, "listening")
        turn, events, final = talk(ws)
        tool = [e for e in events if e["type"] == "tool"]
        assert [(t["name"], t["state"]) for t in tool] == [("calendar_agenda", "running"), ("calendar_agenda", "done")]
        assert tool[0]["text"] == "Looking at your calendar…"
        assert final["text"] == "Let me check. Paris is the capital of France." and turn["saved"] is True
        ws.send_json({"type": "stop"})
        until(ws, "done")
    assert hub.calls == [("calendar_agenda", {"day": "tomorrow"}, "t_1")]
    assert hub.turns[0]["tools"] == [{"name": "calendar_agenda", "arguments": '{"day": "tomorrow"}', "state": "done"}]
    assert json.loads(lines(client, "TOOL_OUTPUT ")[0]) == {"events": [{"time": "10:00", "title": "Dentist"}]}
    session = next(json.loads(s) for s in lines(client, "SESSION ") if json.loads(s)["type"] == "realtime")
    assert [t["name"] for t in session["tools"]] == ["calendar_agenda", "time_now"]         # the unknown one is left out
    assert session["instructions"].startswith("Respond with function calls, and interleaved text and audio.")
    assert len(session["tools"][0]["description"]) <= 330 and session["tools"][0]["type"] == "function"
    assert session["output_modalities"] is None            # with tools, speech isn't forced on the first response


def test_a_first_response_of_text_alone_is_asked_again_to_be_spoken(client, hub, monkeypatch):
    monkeypatch.setenv("FAKE_LLAMA_MODE", "notool")
    monkeypatch.setenv("FAKE_LLAMA_CHUNKS", "0")           # text, no audio
    client.app_.state.voice_mode = {"tools": ["time_now"]}
    with client.websocket_connect("/v1/realtime") as ws:
        ws.send_json({"type": "start"})
        until(ws, "listening")
        turn, events, final = talk(ws, "What is the capital of France?")
        assert final["text"] == "Paris is the capital of France." and turn["assistant"] == final["text"]      # once, not twice
        ws.send_json({"type": "stop"})


def test_what_would_ask_is_refused_aloud(client, hub):
    client.app_.state.voice_mode = {"tools": ["calendar_add"]}
    hub.status = "denied"
    with client.websocket_connect("/v1/realtime") as ws:
        ws.send_json({"type": "start", "thread": "t_1"})
        until(ws, "listening")
        turn, events, _ = talk(ws, "Add a meeting tomorrow at ten")
        assert [(e["name"], e["state"]) for e in events if e["type"] == "tool"][-1] == ("calendar_add", "refused")
        ws.send_json({"type": "stop"})
    told = json.loads(lines(client, "TOOL_OUTPUT ")[0])
    assert "can't be given by voice" in told["refused"] and "changes your calendar" in told["why"]


def test_no_tools_means_no_tools(client, hub):
    client.app_.state.voice_mode = {"tools": [], "ask_chat": False}
    with client.websocket_connect("/v1/realtime") as ws:
        ws.send_json({"type": "start", "thread": "t_1"})
        until(ws, "listening")
        turn, events, final = talk(ws)
        assert final["text"] == "Paris is the capital of France." and not [e for e in events if e["type"] == "tool"]
        ws.send_json({"type": "stop"})
    session = next(json.loads(s) for s in lines(client, "SESSION ") if json.loads(s)["type"] == "realtime")
    assert session["tools"] == [] and session["instructions"].startswith("Respond with interleaved text and audio.")
    assert session["output_modalities"] == ["text", "audio"]


def test_asking_the_chats_model(client, hub, monkeypatch):
    monkeypatch.setenv("FAKE_LLAMA_TOOL", "ask_chat")
    monkeypatch.setenv("FAKE_LLAMA_ARGS", '{"question": "what does the report say about sales"}')
    client.app_.state.voice_mode = {"tools": [], "ask_chat": True}
    with client.websocket_connect("/v1/realtime") as ws:
        ws.send_json({"type": "start", "thread": "t_1"})
        until(ws, "listening")
        turn, events, _ = talk(ws, "What does the report say about sales?")
        assert [(e["name"], e["state"]) for e in events if e["type"] == "tool"] == [("ask_chat", "running"), ("ask_chat", "done")]
        assert turn["saved"] is True
        ws.send_json({"type": "stop"})
    assert hub.asked == ["What does the report say about sales?"]         # your own words, not the model's rewording
    assert hub.turns == []                                                # the chat already holds the question and the answer
    assert json.loads(lines(client, "TOOL_OUTPUT ")[0])["answer"] == "Sales rose nine percent."


async def test_the_toolbox():
    hub = FakeHub()
    box = tools.ToolBox(hub, None, ["time_now", "time_now", *[f"t{i}" for i in range(9)]], ask_chat=True)
    assert len(box.names) == 6 and box.ask_chat is False                  # at most six; no chat, no ask_chat
    await box.load()
    state, out = await box.run("time_now", "{}")
    assert state == "done" and "now" in json.loads(out)
    assert (await box.run("rm_rf", "{}"))[0] == "failed" and (await box.run("t0", "[1]"))[0] == "failed"
    assert (await box.run("t0", "not json"))[0] == "failed"
    hub.status = "running"
    assert "still running" in (await box.run("t0", "{}"))[1]
    assert len(tools.short("x" * 5000)) < 2100 and tools.words_for("web_search") == "Searching the web…"
