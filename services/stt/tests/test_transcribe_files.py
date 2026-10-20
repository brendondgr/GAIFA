"""`POST /v1/transcribe` and `/v1/transcribe/upload` on the mock model: jobs, output files, video
input, and the transcript's shapes (plan 29.1)."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

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
    """Outputs from a dict of id → file, instead of AIHub."""

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
    r = client.post("/v1/transcribe", json={"output_id": "output:abc123", "timestamps": "words"})
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
    assert client.get("/v1/status").json()["loaded"] == "large-v3"
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
    assert client.get("/v1/status").json()["loaded"] is None


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
