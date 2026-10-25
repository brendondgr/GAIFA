"""The routes GAIFA uses, with the engines stubbed: status, speech saving, outputs, the widget."""

import json
import time

import pytest
from fastapi.testclient import TestClient

from localtts import engines, server
from localtts.config import settings


@pytest.fixture
def client(monkeypatch):
    async def ensure_loaded(self):
        self.info = {"sample_rate": 24000}

    async def generate(self, request_id, **params):
        self.last_used = time.monotonic()
        yield b"\x00\x01" * 2400
        yield {"event": "done", "audio_s": 0.1, "gen_s": 0.05, "rtf": 0.5}

    monkeypatch.setattr(engines.Engine, "ensure_loaded", ensure_loaded)
    monkeypatch.setattr(engines.Engine, "generate", generate)
    settings.outputs_dir.mkdir(parents=True, exist_ok=True)
    settings.voices_dir.mkdir(parents=True, exist_ok=True)
    return TestClient(server.app)


def test_status_has_the_gaifa_shape(client):
    s = client.get("/v1/status").json()
    assert s["loaded"] is False and s["busy"] is False and s["idle_s"] is None
    labels = [x["label"] for x in s["stats"]]
    assert labels == ["Voices", "Engines installed", "Clips today"]
    assert s["stats"][1]["value"] == 1          # kokoro's python exists, breeze's doesn't
    assert s["stats"][2]["reset"] == "daily"


def test_speech_is_saved_with_a_sidecar_and_counted(client):
    before = client.get("/v1/status").json()["stats"][2]["value"]
    r = client.post("/v1/speech", json={"text": "Testing one two", "voice": "af_heart", "request_id": "abc"})
    assert r.status_code == 200 and r.headers["content-type"] == "audio/wav"
    saved = r.headers["X-LocalTTS-Saved"]
    day = time.strftime("%Y-%m-%d")
    f = settings.outputs_dir / day / saved
    side = json.loads(f.with_name(f.name + ".json").read_text())
    assert side["voice"] == "af_heart" and side["engine"] == "kokoro" and side["model"] == "kokoro-82m"
    assert side["source"] == {"service": "tts", "request_id": "abc"} and side["duration_s"] == 0.1
    assert client.get("/v1/status").json()["stats"][2]["value"] == before + 1
    listed = client.get("/v1/outputs").json()["files"]
    assert f"{day}/{saved}" in [x["file"] for x in listed]
    assert client.get(f"/v1/outputs/{day}/{saved}").content == f.read_bytes()


def test_openai_route_saves_too_and_no_save_writes_nothing(client):
    n = len(client.get("/v1/outputs").json()["files"])
    assert client.post("/v1/audio/speech", json={"input": "hi", "voice": "af_bella", "response_format": "wav"}).status_code == 200
    assert client.post("/v1/speech", json={"text": "hi", "voice": "af_bella", "no_save": True}).headers["X-LocalTTS-Saved"] == "no"
    assert len(client.get("/v1/outputs").json()["files"]) == n + 1


def test_an_absolute_save_dir_is_refused(client):
    r = client.post("/v1/speech", json={"text": "hi", "voice": "af_heart", "save_dir": "/tmp/elsewhere"})
    assert r.status_code == 400


def test_deleting_an_output_removes_its_sidecar(client):
    saved = client.post("/v1/speech", json={"text": "bye", "voice": "af_heart"}).headers["X-LocalTTS-Saved"]
    rel = f"{time.strftime('%Y-%m-%d')}/{saved}"
    assert client.delete(f"/v1/outputs/{rel}").status_code == 200
    assert not (settings.outputs_dir / (rel + ".json")).exists()
    assert client.get(f"/v1/outputs/{rel}").status_code == 404
    assert client.get("/v1/outputs/../../etc/passwd").status_code == 404


def test_the_clips_widget_is_widget_data(client):
    client.post("/v1/speech", json={"text": "w", "voice": "af_sky"})
    w = client.get("/v1/hub/widgets/clips?range=7d").json()
    assert w["unit"] == "count" and len(w["categories"]) == 7
    sky = next(s for s in w["series"] if s["name"] == "af_sky")
    assert sky["values"][-1] >= 1 and len(sky["values"]) == 7
    assert client.get("/v1/hub/widgets/clips?range=1h").status_code == 422


def test_idle_unload_zero_means_never(monkeypatch):
    import asyncio
    e = engines.Engine("x", settings.kokoro_python, "kokoro_worker.py")

    class Proc:
        returncode = None
        pid = 0
    e.proc, e.state, e.last_used = Proc(), "ready", time.monotonic() - 10_000
    called = []

    async def unload(reason="requested"):
        called.append(reason)
    monkeypatch.setattr(e, "unload", unload)
    object.__setattr__(settings, "idle_unload_s", 0.0)
    try:
        asyncio.run(e.maybe_idle_unload())
        assert called == [] and e.status()["unloads_in_s"] is None
        object.__setattr__(settings, "idle_unload_s", 60.0)
        asyncio.run(e.maybe_idle_unload())
        assert called and called[0].startswith("idle")
    finally:
        object.__setattr__(settings, "idle_unload_s", 180.0)


def test_voices_dir_comes_from_the_environment():
    assert settings.voices_dir.name == "voices" and "localtts-test-" in str(settings.voices_dir)
