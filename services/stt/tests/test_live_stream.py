"""`WS /v1/stream` (plan 29.2) on the mock model: the protocol, and committed text that matches the
file route's. The mock reads position-encoded audio, so both routes see the same scripted words."""

from __future__ import annotations

import json

import numpy as np
import pytest
from conftest import wait_job
from fastapi.testclient import TestClient
from live_helpers import stream, wer
from starlette.websockets import WebSocketDisconnect

from stt.asr.mock import positional_audio
from stt.server import create_app
from test_transcribe_files import LocalHub


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings, hub=LocalHub({}))) as c:
        yield c


def test_stream_commits_what_the_file_route_transcribes(client):
    audio = positional_audio(0.0, 20.0)
    events, done = stream(client, audio, encoding="float32")

    committed = [e for e in events if e["type"] == "committed"]
    assert committed and [e["segment"]["id"] for e in committed] == list(range(1, len(committed) + 1))
    assert any(e["type"] == "hypothesis" and e["text"] for e in events)
    streamed = " ".join(e["segment"]["text"] for e in committed)
    assert streamed == done["text"]
    assert done["duration"] == 20.0 and done["model"] == "small" and "output" not in done

    r = client.post("/v1/transcribe/upload", params={"filename": "positional.wav"},
                    content=_float_wav(audio))
    filed = wait_job(client, r.json()["id"])["result"]["text"]
    assert len(filed.split()) > 30
    assert wer(filed, done["text"]) <= 0.1, (filed, done["text"])


def test_int16_frames_and_a_saved_dictation(client, settings):
    _, done = stream(client, positional_audio(0.0, 6.0), encoding="int16", save=True, title="note to self")
    assert done["output"].startswith("stt/") and done["output"].endswith("note-to-self")
    side = json.loads((settings.outputs.parent / done["output"] / "output.json").read_text())
    assert side["complete"] and side["source"]["live"] is True


def test_another_sample_rate_is_resampled(client):
    audio48 = np.random.default_rng(1).normal(0, 0.1, 48_000 * 2).astype(np.float32)
    _, done = stream(client, audio48, encoding="float32", sample_rate=48_000)
    assert abs(done["duration"] - 2.0) < 0.05


@pytest.mark.parametrize(("first", "detail"), [
    ({"type": "go"}, "start"), ({"type": "start", "encoding": "mp3"}, "encoding"),
    ({"type": "start", "preset": "quick"}, "unknown preset")])
def test_protocol_mistakes_close_with_4400_and_say_why(client, first, detail):
    with client.websocket_connect("/v1/stream") as ws:
        ws.send_json(first)
        err = ws.receive_json()
        assert err["type"] == "error" and detail in err["detail"]
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
    assert closed.value.code == 4400


def test_text_other_than_stop_after_start_is_refused(client):
    with client.websocket_connect("/v1/stream") as ws:
        ws.send_json({"type": "start"})
        assert ws.receive_json()["type"] == "ready"
        ws.send_text("hello")
        assert "stop" in ws.receive_json()["detail"]


def test_an_odd_int16_frame_is_refused(client):
    with client.websocket_connect("/v1/stream") as ws:
        ws.send_json({"type": "start"})
        ws.receive_json()
        ws.send_bytes(b"\x00\x01\x02")
        assert "even number" in ws.receive_json()["detail"]


def _float_wav(samples: np.ndarray) -> bytes:
    import struct

    data = samples.astype("<f4").tobytes()
    fmt = struct.pack("<HHIIHH", 3, 1, 16_000, 64_000, 4, 32)
    return b"RIFF" + struct.pack("<I", 4 + 8 + len(fmt) + 8 + len(data)) + b"WAVE" + \
        b"fmt " + struct.pack("<I", len(fmt)) + fmt + b"data" + struct.pack("<I", len(data)) + data
