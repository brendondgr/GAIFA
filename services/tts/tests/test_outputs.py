"""Output naming and the sidecar GAIFA indexes (architecture §4.7)."""

import json
import time
from pathlib import Path

import pytest

from localtts import outputs


def test_clips_go_in_a_dated_folder_named_after_time_text_and_voice(tmp_path):
    now = time.mktime((2026, 10, 6, 9, 5, 7, 0, 0, -1))
    p = outputs.output_path(tmp_path, "Good morning, everyone! How are you all doing today?", "Brendon", "wav", now=now)
    assert p.parent == tmp_path / "2026-10-06"
    assert p.name == "090507-good-morning-everyone-how-are-you-all-brendon.wav"


def test_a_second_clip_in_the_same_second_gets_a_suffix(tmp_path):
    now = time.time()
    a = outputs.output_path(tmp_path, "hi", "af_heart", "mp3", now=now)
    outputs.write_atomic(a, b"x")
    b = outputs.output_path(tmp_path, "hi", "af_heart", "mp3", now=now)
    assert b.name == a.stem + "-2.mp3"


def test_empty_text_still_gets_a_name(tmp_path):
    assert "-speech-" in outputs.output_path(tmp_path, "!!!", "design", "wav").name


@pytest.mark.parametrize("bad", ["/etc", "../up", "a/../../b", "~/Music"])
def test_save_dir_stays_inside_the_outputs_folder(tmp_path, bad):
    with pytest.raises(ValueError):
        outputs.output_path(tmp_path, "hi", "v", "wav", save_dir=bad)


def test_save_dir_is_a_subfolder(tmp_path):
    p = outputs.output_path(tmp_path, "hi", "v", "wav", save_dir="project/take1")
    assert p.parent == tmp_path / "project" / "take1"


def test_save_writes_the_clip_then_its_sidecar_and_leaves_no_part_files(tmp_path):
    p = outputs.output_path(tmp_path, "Hello there", "hope", "wav")
    meta = outputs.sidecar(text="Hello there", voice="hope", engine="breeze", model="breeze-tts-2",
                           params={"instructions": None, "format": "wav", "seed": 42}, duration_s=1.234,
                           request_id="r1")
    outputs.save(p, b"RIFF", meta)
    assert p.read_bytes() == b"RIFF"
    side = json.loads(p.with_name(p.name + ".json").read_text())
    assert side == {"title": "Hello there", "kind": "audio", "prompt": "Hello there", "voice": "hope",
                    "engine": "breeze", "model": "breeze-tts-2", "params": {"format": "wav", "seed": 42},
                    "duration_s": 1.23, "source": {"service": "tts", "request_id": "r1"}}
    assert not list(tmp_path.rglob("*.part"))


def test_long_titles_are_cut(tmp_path):
    meta = outputs.sidecar(text="word " * 40, voice="v", engine="kokoro", model="kokoro-82m", params={},
                           duration_s=None, request_id="r")
    assert len(meta["title"]) == 80 and meta["title"].endswith("…")


def test_clips_by_day_counts_per_voice_from_sidecars(tmp_path):
    now = time.time()
    for voice in ("hope", "hope", "af_heart"):
        p = outputs.output_path(tmp_path, "x", voice, "wav", now=now)
        outputs.save(p, b"x", {"voice": voice})
    (tmp_path / time.strftime("%Y-%m-%d") / "note.txt").write_text("not a clip")
    labels, counts = outputs.clips_by_day(tmp_path, 7, now=now)
    assert len(labels) == 7 and labels[-1] == time.strftime("%Y-%m-%d")
    assert counts == {"hope": [0] * 6 + [2], "af_heart": [0] * 6 + [1]}
    assert outputs.clips_today(tmp_path) == 3


def test_resolve_refuses_escapes_and_dotfiles(tmp_path):
    (tmp_path / "2026-10-06").mkdir()
    f = tmp_path / "2026-10-06" / "a.wav"
    f.write_bytes(b"x")
    (tmp_path / ".trash").mkdir()
    (tmp_path / ".trash" / "b.wav").write_bytes(b"x")
    assert outputs.resolve(tmp_path, "2026-10-06/a.wav") == f.resolve()
    assert outputs.resolve(tmp_path, "../x") is None
    assert outputs.resolve(tmp_path, ".trash/b.wav") is None
    assert outputs.resolve(tmp_path, "2026-10-06") is None
