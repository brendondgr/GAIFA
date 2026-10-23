"""Plan 45.4: speech as a job: lines spoken (an estimate), the audio while it's made, the clip saved at the end,
cancel, and the status jobs; POST /v1/speech is unchanged."""

import asyncio
import time

import pytest
from fastapi.testclient import TestClient

from localtts import engines, jobs, server
from localtts.config import settings

TEXT = "Shall I compare thee to a summer's day?\nThou art more lovely and more temperate.\nRough winds do shake the darling buds of May."


@pytest.fixture
def client(monkeypatch):
    async def ensure_loaded(self):
        self.info = {"sample_rate": 24000}

    async def generate(self, request_id, **params):
        self.info = {"sample_rate": 24000}
        for _ in range(4):
            await asyncio.sleep(0.15)
            yield b"\x00\x01" * 24000          # a second of audio per chunk
        yield {"event": "done", "audio_s": 4.0, "gen_s": 0.6, "rtf": 0.15}

    monkeypatch.setattr(engines.Engine, "ensure_loaded", ensure_loaded)
    monkeypatch.setattr(engines.Engine, "generate", generate)
    settings.outputs_dir.mkdir(parents=True, exist_ok=True)
    settings.voices_dir.mkdir(parents=True, exist_ok=True)
    with TestClient(server.app) as c:
        yield c


def test_lines_and_their_estimate():
    assert jobs.lines_of("a\n\n b ") == ["a", "b"]
    long = "One sentence here. " * 12
    assert len(jobs.lines_of(long)) == 12
    assert jobs.lines_done(TEXT, 0, False) == [0, 3]
    assert jobs.lines_done(TEXT, 3.5, False) == [1, 3]
    assert jobs.lines_done(TEXT, 99, False) == [2, 3]
    assert jobs.lines_done(TEXT, 1, True) == [3, 3]


def test_a_speech_job_streams_then_saves(client):
    r = client.post("/v1/speech/jobs", json={"text": TEXT, "name": "af_heart"})
    assert r.status_code == 202
    jid = r.json()["id"]
    got, offset, seen_live = b"", 0, None
    t0 = time.monotonic()
    while time.monotonic() - t0 < 10:
        a = client.get(f"/v1/speech/jobs/{jid}/audio", params={"offset": offset, "wait": 2})
        assert a.headers["x-sample-rate"] == "24000"
        got += a.content
        offset += len(a.content)
        st = client.get(f"/v1/speech/jobs/{jid}").json()
        if st.get("live"):
            seen_live = st["live"]
        if a.headers["x-done"] == "1":
            break
    assert len(got) == 4 * 48000
    assert seen_live and seen_live["audio"] == f"/v1/speech/jobs/{jid}/audio" and seen_live["lines"][1] == 3
    done = client.get(f"/v1/speech/jobs/{jid}").json()
    assert done["state"] == "done" and done["progress"] == 1.0 and "live" not in done
    path = done["outputs"][0]["path"]
    assert path.endswith(".wav") and done["outputs"][0]["kind"] == "audio"
    assert (settings.outputs_dir / path).exists() or __import__("pathlib").Path(path).exists()


def test_status_lists_a_running_speech_job_with_live(client):
    jid = client.post("/v1/speech/jobs", json={"text": TEXT, "name": "af_heart"}).json()["id"]
    t0 = time.monotonic()
    found = None
    while time.monotonic() - t0 < 5 and not found:
        found = next((j for j in client.get("/v1/status").json()["jobs"] if j["id"] == f"speech-{jid}" and j.get("live")), None)
        time.sleep(0.05)
    assert found and found["state"] in ("queued", "running") and found["route"] == "#/s/tts"
    client.get(f"/v1/speech/jobs/{jid}/audio", params={"offset": 10 ** 9, "wait": 5})


def test_cancel_and_unknown(client):
    jid = client.post("/v1/speech/jobs", json={"text": TEXT, "name": "af_heart", "no_save": True}).json()["id"]
    assert client.post(f"/v1/speech/jobs/{jid}/cancel").json()["state"] == "cancelled"
    assert client.get("/v1/speech/jobs/s_nope").status_code == 404
    assert client.post("/v1/speech/jobs", json={"text": "  "}).status_code == 400


def test_the_old_route_is_unchanged(client):
    r = client.post("/v1/speech", json={"text": "Hello there.", "name": "af_heart", "no_save": True})
    assert r.status_code == 200 and r.headers["content-type"].startswith("audio/wav")
