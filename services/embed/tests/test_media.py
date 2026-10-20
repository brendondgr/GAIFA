"""Decoding: audio to 16 kHz mono, video at 1 fps (sampled evenly past the frame budget), images to RGB."""

from __future__ import annotations

import pytest
from PIL import Image

from embed import media
from tests.conftest import mp4, png, wav


def test_audio_is_16k_mono(tmp_path):
    p = media.audio(wav(3, rate=44100, channels=2), max_s=320, tmp_dir=tmp_path)
    assert p.value["sampling_rate"] == 16000 and p.value["array"].ndim == 1
    assert abs(p.value["array"].size - 48000) < 200 and p.info == {"seconds": 3.0}
    assert list(tmp_path.iterdir()) == []                                # the temporary copy is gone


def test_long_audio_is_cut_to_the_context(tmp_path):
    p = media.audio(wav(5, rate=16000, channels=1), max_s=2, tmp_dir=tmp_path)
    assert p.value["array"].size == 32000 and p.info == {"seconds": 2, "truncated": True}


def test_video_frames_at_one_fps(tmp_path):
    p = media.video(mp4(tmp_path, 6), max_frames=32, tmp_dir=tmp_path / "t")
    assert len(p.value) == 6 and all(isinstance(f, Image.Image) and f.size == (160, 120) for f in p.value)
    assert p.info["fps"] == 1.0 and abs(p.info["seconds"] - 6) < 0.2


def test_long_video_is_sampled_to_the_budget(tmp_path):
    p = media.video(mp4(tmp_path, 12), max_frames=4, tmp_dir=tmp_path / "t")
    assert len(p.value) == 4 and p.info["fps"] < 1


def test_image_and_bad_input(tmp_path):
    p = media.image(png("x", size=(30, 20)))
    assert p.value.mode == "RGB" and p.info == {"width": 30, "height": 20}
    with pytest.raises(media.MediaError):
        media.image(b"nope")
    with pytest.raises(media.MediaError):
        media.audio(b"nope", 10, tmp_path)
    with pytest.raises(media.MediaError):
        media.video(png("x"), 4, tmp_path)
