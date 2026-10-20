"""Any audio or video file → canonical audio (16 kHz mono float32), with ffmpeg.

Video is transcribed from its audio track. A 16-bit PCM WAV is read with the standard library when
ffmpeg is missing, so the fixtures and tests need nothing installed.
"""

from __future__ import annotations

import shutil
import subprocess
import wave
from pathlib import Path

import numpy as np

from .formats import SAMPLE_RATE
from .resample import resample

#: Twelve hours of audio; anything longer is refused rather than filling memory (~2.7 GB).
MAX_SECONDS = 12 * 3600


class DecodeError(ValueError):
    """The file has no audio this can read. The message says why."""


def probe_duration(path: Path) -> float | None:
    """The file's duration in seconds, from ffprobe, or None."""
    exe = shutil.which("ffprobe")
    if exe is None:
        return None
    try:
        out = subprocess.run([exe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                             capture_output=True, text=True, timeout=30, check=False).stdout.strip()
        return float(out) if out and out != "N/A" else None
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def decode(path: Path | str) -> np.ndarray:
    """Read ``path`` as canonical audio: 16 kHz, mono, float32 in −1…1."""
    source = Path(path)
    if not source.is_file():
        raise DecodeError(f"{source.name}: no such file")
    exe = shutil.which("ffmpeg")
    if exe is None:
        return read_wav(source)
    cmd = [exe, "-nostdin", "-v", "error", "-i", str(source), "-map", "0:a:0", "-vn", "-ac", "1",
           "-ar", str(SAMPLE_RATE), "-t", str(MAX_SECONDS), "-f", "f32le", "-"]
    try:
        run = subprocess.run(cmd, capture_output=True, timeout=1800, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise DecodeError(f"{source.name}: ffmpeg failed ({exc})") from exc
    if run.returncode != 0:
        err = run.stderr.decode("utf-8", "replace")
        lines = err.strip().splitlines()
        detail = lines[-1] if lines else f"exit code {run.returncode}"
        if "matches no streams" in err:
            detail = "it has no audio track"
        raise DecodeError(f"{source.name}: couldn't read audio: {detail}")
    samples = np.frombuffer(run.stdout, dtype="<f4").astype(np.float32, copy=True)
    return np.clip(samples, -1.0, 1.0)


def read_wav(path: Path) -> np.ndarray:
    """A PCM WAV (8/16/32-bit, any rate, any channels) without ffmpeg."""
    try:
        with wave.open(str(path), "rb") as handle:
            channels, width, rate = handle.getnchannels(), handle.getsampwidth(), handle.getframerate()
            frames = handle.readframes(handle.getnframes())
    except (wave.Error, OSError, EOFError) as exc:
        raise DecodeError(f"{path.name}: not a WAV this can read without ffmpeg ({exc})") from exc
    if width == 2:
        samples = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    elif width == 4:
        samples = np.frombuffer(frames, dtype="<i4").astype(np.float32) / 2147483648.0
    elif width == 1:
        samples = (np.frombuffer(frames, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    else:
        raise DecodeError(f"{path.name}: {width * 8}-bit WAV isn't supported")
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    if rate != SAMPLE_RATE:
        samples = resample(samples, rate, SAMPLE_RATE)
    return samples.astype(np.float32, copy=False)


def pcm_frame(data: bytes, encoding: str) -> np.ndarray:
    """One binary frame from a live stream: little-endian ``int16`` or ``float32`` samples."""
    if encoding == "int16":
        if len(data) % 2:
            raise DecodeError("an int16 frame must have an even number of bytes")
        return np.frombuffer(data, dtype="<i2").astype(np.float32) / 32768.0
    if encoding == "float32":
        if len(data) % 4:
            raise DecodeError("a float32 frame must be a multiple of 4 bytes")
        return np.clip(np.frombuffer(data, dtype="<f4").astype(np.float32), -1.0, 1.0)
    raise DecodeError(f"unknown encoding {encoding!r}; use int16 or float32")
