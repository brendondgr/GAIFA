"""Decoding: audio to 16 kHz mono, video at 1 fps (sampled evenly past the frame budget), images to RGB."""

from __future__ import annotations

import io
import shutil
import subprocess

import pytest
from PIL import Image, PngImagePlugin

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


def _in_time(fn, s: float = 5):
    """Run `fn` in a thread: a parser that never ends fails the test instead of hanging it."""
    import threading
    out: dict = {}

    def go():
        try:
            out["value"] = fn()
        except Exception as e:                      # noqa: BLE001
            out["error"] = e
    t = threading.Thread(target=go, daemon=True)
    t.start()
    t.join(s)
    assert not t.is_alive(), "never ended"
    if "error" in out:
        raise out["error"]
    return out["value"]


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="no ffmpeg")
def test_ten_bit_video(tmp_path):
    """ffmpeg's ppm for a 10-bit video is 16 bits a channel unless asked for rgb24."""
    out = tmp_path / "v10.mkv"
    r = subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                        "testsrc=duration=3:size=64x48:rate=4", "-c:v", "ffv1", "-pix_fmt", "yuv420p10le", str(out)])
    if r.returncode != 0:
        pytest.skip("this ffmpeg can't write 10-bit ffv1")
    p = media.video(out.read_bytes(), max_frames=32, tmp_dir=tmp_path / "t")
    assert len(p.value) == 3 and p.value[0].size == (64, 48) and p.value[0].mode == "RGB"


@pytest.mark.parametrize("raw", [b"P6 16", b"P6", b"P6 2 2 255\n" + bytes(5), b"P6 2 2 65535\n" + bytes(24),
                                 b"P6 " + b"9" * 100])
def test_frames_cut_short_or_in_another_format_are_an_error(raw):
    with pytest.raises(media.MediaError):
        _in_time(lambda: media.ppm_frames(raw))


def test_large_images_are_scaled_down_and_huge_ones_refused():
    buf = io.BytesIO()
    meta = PngImagePlugin.PngInfo()
    meta.add_text("label", "big")
    Image.new("RGB", (4000, 1000), "blue").save(buf, "PNG", pnginfo=meta)
    p = media.image(buf.getvalue())
    w, h = p.value.size
    assert w * h <= media.IMAGE_PIXELS and abs(w / h - 4) < 0.05 and p.value.mode == "RGB"
    assert p.info == {"width": 4000, "height": 1000} and p.value.info.get("label") == "big"
    buf = io.BytesIO()
    Image.new("RGB", (4000, 3000), "green").save(buf, "JPEG")
    p = media.image(buf.getvalue())                                  # decoded at a smaller size, then fitted
    assert p.value.width * p.value.height <= media.IMAGE_PIXELS and p.info == {"width": 4000, "height": 3000}
    buf = io.BytesIO()
    Image.new("1", (9000, 9000)).save(buf, "PNG")                    # 81 MP: a few KB on disk, 243 MB decoded
    with pytest.raises(media.MediaError, match="81 MP"):
        media.image(buf.getvalue())
    buf = io.BytesIO()
    Image.new("1", (14000, 14000)).save(buf, "PNG")                  # past PIL's own bomb limit: a 415, not a 500
    with pytest.raises(media.MediaError):
        media.image(buf.getvalue())
