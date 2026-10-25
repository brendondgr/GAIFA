"""`POST /v1/transcribe` and `/v1/transcribe/upload` on the mock model: jobs, output files, video
input, and the transcript's shapes (plan 29.1)."""

from __future__ import annotations

import asyncio
import contextlib
import json
import shutil
import subprocess
import time
from pathlib import Path

import numpy as np
import pytest
from conftest import ALTERNATING, SEMINAR, SILENT, wait_job
from fastapi.testclient import TestClient

from stt import transcripts
from stt.asr.contract import WordToken
from stt.audio.decode import decode
from stt.hub import Hub, HubError
from stt.segment import Segment
from stt.server import create_app


class LocalHub(Hub):
    """Outputs from a dict of id → file, instead of GAIFA."""

    def __init__(self, files: dict[str, Path]) -> None:
        super().__init__("http://hub.invalid")
        self.files = files
        self.registered: list[str] = []

    async def fetch_output(self, ref, folder, name):
        oid = ref.split(":", 1)[-1]
        if oid not in self.files:
            raise HubError(f"no output {oid!r}")
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{name}{self.files[oid].suffix}"
        shutil.copy(self.files[oid], path)
        return path, {"title": self.files[oid].stem, "kind": "audio"}

    async def register_model(self, name, fetched):
        self.registered.append(name)


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings, hub=LocalHub({"abc123": SEMINAR, "quiet": SILENT}))) as c:
        yield c


def upload(client, path: Path, **query) -> dict:
    r = client.post("/v1/transcribe/upload", params={"filename": path.name, **query}, content=path.read_bytes())
    assert r.status_code == 202, r.text
    return wait_job(client, r.json()["id"])


def test_an_upload_becomes_a_folder_output_with_md_srt_and_words(client, settings):
    job = upload(client, ALTERNATING)
    assert job["state"] == "done", job
    res = job["result"]
    assert res["text"] and res["duration"] == 20.0 and res["model"] == "small"
    assert res["segments"][0]["start"] == 0.0 and "words" not in res["segments"][0]

    folder = settings.outputs.parent / res["output"]
    assert folder.parent.parent == settings.outputs                       # outputs/stt/<date>/<HHMMSS>-<slug>
    side = json.loads((folder / "output.json").read_text())
    assert side["complete"] is True and side["kind"] == "text" and side["main"] == "transcript.md"
    md = (folder / "transcript.md").read_text()
    assert md.startswith("# alternating 20s") and "\n[00:00] " in md
    assert (folder / "transcript.srt").read_text().startswith("1\n00:00:00,000 --> ")
    words = json.loads((folder / "words.json").read_text())
    assert words["segments"][0]["words"][0]["start"] == 0.0
    assert not list(folder.glob("*.part"))
    assert set(res["files"]) == {"markdown", "srt", "words"}


def test_an_output_id_is_fetched_from_the_hub(client):
    r = client.post("/v1/transcribe", json={"audio": "output:abc123", "timestamps": "words"})
    job = wait_job(client, r.json()["id"])
    assert job["state"] == "done" and job["label"] == "seminar-speech-real"
    assert job["result"]["segments"][0]["words"]
    assert job["source"] == {"output_id": "output:abc123"}


def test_a_missing_output_fails_the_job_with_a_reason(client):
    job = wait_job(client, client.post("/v1/transcribe", json={"output_id": "output:nope"}).json()["id"])
    assert job["state"] == "failed" and "no output 'nope'" in job["error"]


def test_silence_gives_an_empty_transcript_not_invented_text(client, settings):
    job = upload(client, SILENT)
    assert job["state"] == "done" and job["result"]["text"] == ""
    assert "(no speech found)" in (settings.outputs.parent / job["result"]["output"] / "transcript.md").read_text()


def test_timestamps_none_leaves_the_segments_out_and_save_false_writes_nothing(client, settings):
    job = upload(client, ALTERNATING, timestamps="none", save="false")
    assert "segments" not in job["result"] and "output" not in job["result"]
    assert not settings.outputs.exists()


def test_presets_and_models_pick_what_loads(client):
    assert upload(client, ALTERNATING, preset="fast")["model"] == "base"
    assert upload(client, ALTERNATING, model="large-v3", preset="fast")["model"] == "large-v3"
    st = client.get("/v1/status").json()
    assert st["loaded"] is True and st["engine"]["model"] == "large-v3"
    r = client.post("/v1/transcribe", json={"output_id": "output:abc123", "preset": "quick"})
    assert r.status_code == 422


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
def test_a_video_is_transcribed_from_its_audio_track(client, tmp_path):
    video = tmp_path / "talk.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=64x64:r=5", "-i", str(SEMINAR),
                    "-shortest", "-c:v", "libx264", "-c:a", "aac", str(video)], check=True)
    assert abs(decode(video).size / 16_000 - 25.3) < 0.3
    job = upload(client, video)
    assert job["state"] == "done" and job["result"]["text"] and abs(job["duration"] - 25.3) < 0.3


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
def test_a_video_without_sound_says_so(client, tmp_path):
    video = tmp_path / "mute.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=64x64:r=5", "-t", "1",
                    "-c:v", "libx264", str(video)], check=True)
    job = upload(client, video)
    assert job["state"] == "failed" and "no audio track" in job["error"]


def test_load_unload_and_models(client):
    assert client.post("/v1/load", json={}).json()["model"] == "small"
    models = client.get("/v1/models").json()
    assert models["default"] == "small" and models["presets"]["balanced"] == "small"
    assert next(m for m in models["models"] if m["name"] == "small")["loaded"] is True
    assert client.post("/v1/unload").json()["state"] == "unloaded"
    assert client.get("/v1/status").json()["loaded"] is False


def test_status_has_the_hub_shape(client):
    upload(client, ALTERNATING)
    st = client.get("/v1/status").json()
    assert set(st) >= {"loaded", "busy", "idle_s", "stats", "jobs"}
    assert len(st["stats"]) <= 4 and all(s["label"] for s in st["stats"])
    assert st["jobs"][0]["state"] == "done"


def test_markdown_paragraphs_break_at_pauses_and_hours_get_their_own_field():
    seg = lambda i, a, b, t: Segment(id=i, text=t, start=a, end=b, words=[WordToken(t, a, b)])  # noqa: E731
    segs = [seg(1, 0, 4, "One."), seg(2, 4.2, 8, "Two."), seg(3, 12, 15, "Three."), seg(4, 3725, 3727, "Late.")]
    md = transcripts.markdown(segs, title="T", duration=3727, model="small", language="en")
    assert "\n[00:00] One. Two.\n" in md and "\n[00:12] Three.\n" in md and "\n[1:02:05] Late.\n" in md
    assert transcripts.srt(segs[:1]) == "1\n00:00:00,000 --> 00:00:04,000\nOne.\n\n"


# -- runtime/tmp: uploads never outlive their job, and the queue has a ceiling --------------------------

@pytest.fixture
def held(monkeypatch):
    """Decoding blocks until ``held.set()``, so the first job stays running and the rest stay queued."""
    import threading

    import stt.jobs

    gate = threading.Event()
    real = stt.jobs.decode
    monkeypatch.setattr(stt.jobs, "decode", lambda path: (gate.wait(30), real(path))[1])
    yield gate
    gate.set()


def _send(client, name: str = "a.wav"):
    return client.post("/v1/transcribe/upload", params={"filename": name, "save": "false"},
                       content=ALTERNATING.read_bytes())


def test_cancelling_a_queued_upload_deletes_its_file_at_once(settings, tmp_dir, held):
    with TestClient(create_app(settings, hub=LocalHub({}))) as client:
        first, queued = _send(client, "first.wav").json(), _send(client, "queued.wav").json()
        assert any("queued" in p.name for p in tmp_dir.iterdir())
        assert client.post(f"/v1/jobs/{queued['id']}/cancel").json()["state"] == "cancelled"
        assert not any("queued" in p.name for p in tmp_dir.iterdir())
        held.set()
        assert wait_job(client, first["id"])["state"] == "done"
        time.sleep(0.1)
        assert list(tmp_dir.iterdir()) == []


def test_waiting_uploads_are_capped_with_a_429(settings, tmp_dir, held, monkeypatch):
    import stt.server

    monkeypatch.setattr(stt.server, "MAX_QUEUED_UPLOADS", 2)
    with TestClient(create_app(settings, hub=LocalHub({}))) as client:
        assert _send(client).status_code == 202                  # running (held in decoding)
        deadline = time.monotonic() + 5
        while client.get("/v1/jobs").json()["jobs"][0]["state"] != "running":
            assert time.monotonic() < deadline
            time.sleep(0.02)
        assert _send(client).status_code == 202 and _send(client).status_code == 202
        r = _send(client)
        assert r.status_code == 429 and r.json()["code"] == "queue_full" and "cancel" in r.json()["fix"]
        assert len(list(tmp_dir.iterdir())) == 3                 # the refused one wrote nothing
        held.set()


def test_an_upload_cut_off_midway_leaves_no_file(settings, tmp_dir):
    app = create_app(settings, hub=LocalHub({}))
    messages = iter([{"type": "http.request", "body": b"RIFF" + b"\0" * 4096, "more_body": True},
                     {"type": "http.disconnect"}])
    sent: list[dict] = []

    async def receive():
        return next(messages)

    async def send(message):
        sent.append(message)

    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "POST",
             "scheme": "http", "path": "/v1/transcribe/upload", "raw_path": b"/v1/transcribe/upload",
             "query_string": b"filename=cut.wav", "root_path": "", "headers": [], "server": ("t", 80),
             "client": ("t", 1)}
    with contextlib.suppress(Exception):
        asyncio.run(app(scope, receive, send))
    assert tmp_dir.is_dir() and list(tmp_dir.iterdir()) == []
    assert app.state.jobs.list() == [] and app.state.jobs.receiving == 0


def test_a_full_disk_mid_upload_answers_507_and_leaves_no_file(settings, tmp_dir, monkeypatch):
    import errno
    import pathlib

    real_open = pathlib.Path.open

    class Full:
        def __init__(self, f):
            self.f = f

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.f.close()

        def write(self, data):
            raise OSError(errno.ENOSPC, "No space left on device")

    def opener(self, *args, **kwargs):
        f = real_open(self, *args, **kwargs)
        return Full(f) if self.parent == tmp_dir else f

    monkeypatch.setattr(pathlib.Path, "open", opener)
    with TestClient(create_app(settings, hub=LocalHub({}))) as client:
        r = _send(client)
    assert r.status_code == 507 and r.json()["code"] == "no_space" and "No space" in r.json()["detail"]
    assert list(tmp_dir.iterdir()) == []


def test_files_left_in_runtime_tmp_by_a_crash_are_swept_at_startup(settings, tmp_dir):
    import os

    tmp_dir.mkdir(parents=True)
    old_file, old_job, fresh = tmp_dir / "upload-1-old.wav", tmp_dir / "j_old", tmp_dir / "upload-2-new.wav"
    old_file.write_bytes(b"x" * 1000)
    old_job.mkdir()
    (old_job / "input.wav").write_bytes(b"x")
    fresh.write_bytes(b"x")                                    # maybe another instance's upload
    for p in (old_job / "input.wav", old_job, old_file):
        os.utime(p, (time.time() - 7200, time.time() - 7200))
    with TestClient(create_app(settings, hub=LocalHub({}))):
        pass
    assert sorted(p.name for p in tmp_dir.iterdir()) == ["upload-2-new.wav"]


# -- decoding keeps one copy of the audio in memory --------------------------------------------------

PEAK_SCRIPT = """
import sys
import numpy as np
from stt.audio.decode import decode
def peak():   # this process's own high-water mark (ru_maxrss can carry the parent's across fork + exec)
    return next(int(l.split()[1]) * 1024 for l in open("/proc/self/status") if l.startswith("VmHWM"))
decode(sys.argv[2])                                       # warm up: imports, ffmpeg, the allocator
before = peak()
samples = decode(sys.argv[1])
print((peak() - before) / samples.nbytes)
"""


def _sine_wav(path: Path, seconds: int) -> Path:
    import wave

    with wave.open(str(path), "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(16_000)
        w.writeframes((np.sin(np.arange(16_000 * seconds) / 9) * 9000).astype("<i2").tobytes())
    return path


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
def test_decoding_peaks_at_about_one_copy_of_the_audio(tmp_path):
    """Twenty minutes (77 MB as float32) in a fresh process: the peak grows by about one copy, where
    the bytes from ffmpeg plus a converted and a clipped copy made it about three."""
    import sys

    long, short = _sine_wav(tmp_path / "long.wav", 1200), _sine_wav(tmp_path / "short.wav", 1)
    out = subprocess.run([sys.executable, "-c", PEAK_SCRIPT, str(long), str(short)], capture_output=True,
                         text=True, check=True, cwd=Path(__file__).parent.parent)
    assert float(out.stdout) < 1.35, f"peak grew by {float(out.stdout):.2f}× the audio"


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
def test_decoding_without_a_known_duration_grows_the_buffer(tmp_path, monkeypatch):
    import stt.audio.decode as dec

    monkeypatch.setattr(dec, "probe_duration", lambda path: None)
    monkeypatch.setattr(dec, "FIRST_SECONDS", 1)
    monkeypatch.setattr(dec, "READ_BYTES", 10_000)                 # not a multiple of 4: reads split samples
    samples = dec.decode(SEMINAR)
    assert samples.dtype == np.float32 and np.array_equal(samples, dec.read_wav(SEMINAR))
