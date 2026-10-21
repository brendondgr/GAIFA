"""Input limits: reference uploads (size, length, formats ffmpeg may open), voice design, instructions."""

import asyncio
import subprocess
import time

import pytest
from fastapi.testclient import TestClient

from localtts import audio, engines, server, voices
from localtts.config import settings

calls: list[dict] = []
DONE = {"event": "done", "audio_s": 8.0, "gen_s": 1.0, "rtf": 0.1}


@pytest.fixture
def client(monkeypatch):
    calls.clear()

    async def ensure_loaded(self):
        self.info = {"sample_rate": 24000}

    async def generate(self, request_id, **params):
        calls.append(params)
        yield b"\x00\x01" * 2400
        yield dict(DONE)

    monkeypatch.setattr(engines.Engine, "ensure_loaded", ensure_loaded)
    monkeypatch.setattr(engines.Engine, "generate", generate)
    settings.outputs_dir.mkdir(parents=True, exist_ok=True)
    settings.voices_dir.mkdir(parents=True, exist_ok=True)
    return TestClient(server.app)


def _tone(path, seconds: float, *extra: str):
    subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    f"sine=f=220:d={seconds}", *extra, str(path)], check=True)
    return path


def _upload(client, name, path, filename=None, transcript="hello there"):
    with open(path, "rb") as fh:
        return client.post("/v1/voices", data={"name": name, "transcript": transcript},
                           files={"audio": (filename or path.name, fh.read())})


# ---- reference audio ---------------------------------------------------------------------

def test_decoding_stops_just_past_the_limit(tmp_path):
    src = _tone(tmp_path / "long.flac", 600)   # 10 minutes: decoded whole it would be ~29 MB
    dst = tmp_path / "out.wav"
    with pytest.raises(audio.TooLong):
        asyncio.run(audio.to_reference_wav(str(src), str(dst), max_s=60))
    assert audio.duration_s(str(dst)) <= 61.01 and dst.stat().st_size < 3_000_000


def test_a_long_reference_is_refused_with_422(client, tmp_path):
    r = _upload(client, "Longwind", _tone(tmp_path / "long.flac", 120))
    assert r.status_code == 422 and "over 60s" in r.json()["detail"]
    assert voices.get("Longwind") is None


def test_a_stuck_decode_times_out(tmp_path, monkeypatch):
    fake = tmp_path / "ffmpeg"
    fake.write_text("#!/bin/sh\nexec sleep 20\n")
    fake.chmod(0o755)
    monkeypatch.setattr(audio.shutil, "which", lambda _: str(fake))
    monkeypatch.setattr(audio, "DECODE_TIMEOUT_S", 0.5)
    t0 = time.monotonic()
    with pytest.raises(ValueError, match="took over"):
        asyncio.run(audio.to_reference_wav(str(tmp_path / "x.wav"), str(tmp_path / "y.wav")))
    assert time.monotonic() - t0 < 5


def test_a_playlist_cannot_pull_in_another_local_file(client, tmp_path):
    secret = _tone(tmp_path / "private.mp3", 5)
    playlist = tmp_path / "ref.m3u8"
    playlist.write_text(f"#EXTM3U\n#EXT-X-TARGETDURATION:10\n#EXTINF:5,\n{secret}\n#EXT-X-ENDLIST\n")
    r = _upload(client, "Sneaky", playlist)
    assert r.status_code == 400 and "playlists" in r.json()["detail"]
    assert voices.get("Sneaky") is None
    concat = tmp_path / "list.ffconcat"
    concat.write_text(f"ffconcat version 1.0\nfile '{secret}'\n")
    with pytest.raises(ValueError, match="playlists"):
        asyncio.run(audio.to_reference_wav(str(concat), str(tmp_path / "c.wav")))


@pytest.mark.parametrize("ext", ["m4a", "webm", "ogg", "mp3", "flac"])
def test_common_formats_still_decode(tmp_path, ext):
    dst = tmp_path / "out.wav"
    asyncio.run(audio.to_reference_wav(str(_tone(tmp_path / f"in.{ext}", 4)), str(dst)))
    assert 3.9 < audio.duration_s(str(dst)) < 4.1


def test_a_good_reference_is_saved(client, tmp_path):
    r = _upload(client, "Toney", _tone(tmp_path / "ok.m4a", 4))
    assert r.status_code == 201, r.text
    assert 3.9 < r.json()["duration_s"] < 4.1
    voices.delete("Toney")


def test_uploads_over_the_cap_get_413(client, tmp_path, monkeypatch):
    monkeypatch.setitem(server.MAX_UPLOAD_BYTES, "/v1/voices", 4096)
    big = tmp_path / "big.wav"
    big.write_bytes(b"\0" * 8192)
    r = _upload(client, "Biggie", big)                 # Content-Length says so up front
    assert r.status_code == 413 and "over" in r.json()["detail"]

    def chunks():                                       # chunked: no Content-Length, counted as it arrives
        yield b"--b\r\nContent-Disposition: form-data; name=\"name\"\r\n\r\nBiggie\r\n"
        yield b"--b\r\nContent-Disposition: form-data; name=\"audio\"; filename=\"a.wav\"\r\n\r\n"
        yield b"\0" * 8192
        yield b"\r\n--b--\r\n"
    r = client.post("/v1/voices", content=chunks(), headers={"content-type": "multipart/form-data; boundary=b"})
    assert r.status_code == 413
    monkeypatch.setitem(server.MAX_UPLOAD_BYTES, "/v1/align", 4096)
    r = client.post("/v1/align", data={"items": '[{"id": "a", "text": "hi"}]'}, files={"audio_a": ("a.wav", b"\0" * 8192)})
    assert r.status_code == 413


def test_align_caps_each_clip_at_its_own_limit(client, tmp_path, monkeypatch):
    monkeypatch.setattr(server, "MAX_ALIGN_S", 5.0)
    with open(_tone(tmp_path / "clip.flac", 20), "rb") as fh:
        r = client.post("/v1/align", data={"items": '[{"id": "a", "text": "hi"}]'}, files={"audio_a": ("clip.flac", fh.read())})
    assert r.status_code == 422 and "over 5s" in r.json()["detail"]


# ---- voice design and instructions ---------------------------------------------------------

@pytest.mark.parametrize("field,value", [("sample_text", "x" * 601), ("instruction", "y" * 1001),
                                         ("cfg_scale", 50), ("cfg_scale", 0)])
def test_design_limits_refuse_before_generating(client, field, value):
    body = {"name": "Designy", "instruction": "a calm narrator", field: value}
    assert client.post("/v1/voices/design", json=body).status_code == 422
    assert calls == []


def test_a_designed_sample_must_fit_the_reference_length(client, monkeypatch):
    monkeypatch.setitem(DONE, "audio_s", 75.0)
    r = client.post("/v1/voices/design", json={"name": "Rambler", "instruction": "a slow, rambling storyteller"})
    assert r.status_code == 422 and "75.0s" in r.json()["detail"]
    assert voices.get("Rambler") is None
    monkeypatch.setitem(DONE, "audio_s", 8.0)
    r = client.post("/v1/voices/design", json={"name": "Rambler", "instruction": "a slow, rambling storyteller"})
    assert r.status_code == 201
    voices.delete("Rambler")


def test_speech_instructions_are_capped(client):
    long = "z" * 1001
    assert client.post("/v1/speech", json={"text": "hi", "instruction": long}).status_code == 422
    assert client.post("/v1/audio/speech", json={"input": "hi", "instructions": long}).status_code == 422
    assert calls == []
