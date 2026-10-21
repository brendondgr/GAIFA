"""Any audio or video file → canonical audio (16 kHz mono float32), with ffmpeg.

Video is transcribed from its audio track. A 16-bit PCM WAV is read with the standard library when
ffmpeg is missing, so the fixtures and tests need nothing installed.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import threading
import wave
from pathlib import Path

import numpy as np

from .formats import SAMPLE_RATE
from .resample import resample

#: Twelve hours of audio; anything longer is cut there rather than filling memory. ffmpeg's float32
#: output is read straight into one array that grows in place, so twelve hours peak at about 2.8 GB
#: (16 kHz × 4 bytes × 43,200 s), one copy, not the bytes plus a converted and a clipped copy.
MAX_SECONDS = 12 * 3600
READ_BYTES = 4 << 20             # one read from ffmpeg's pipe
FIRST_SECONDS = 600              # the buffer's first size when ffprobe can't say how long the file is
DECODE_TIMEOUT_S = 1800


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
    seconds = probe_duration(source)
    first = min(seconds + 1, MAX_SECONDS) if seconds else FIRST_SECONDS
    with tempfile.TemporaryFile() as stderr:
        try:
            proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=stderr, bufsize=0)
        except OSError as exc:
            raise DecodeError(f"{source.name}: ffmpeg failed ({exc})") from exc
        timed_out = threading.Event()
        timer = threading.Timer(DECODE_TIMEOUT_S, lambda: (timed_out.set(), proc.kill()))
        timer.start()
        try:
            samples = _read_f32(proc.stdout, int(first * SAMPLE_RATE))
            code = proc.wait()
        finally:
            timer.cancel()
            proc.stdout.close()
            if proc.poll() is None:
                proc.kill()
                proc.wait()
        if code != 0:
            stderr.seek(0)
            err = stderr.read(1 << 20).decode("utf-8", "replace")
            lines = err.strip().splitlines()
            detail = lines[-1] if lines else f"exit code {code}"
            if "matches no streams" in err:
                detail = "it has no audio track"
            elif timed_out.is_set():
                detail = f"ffmpeg took longer than {DECODE_TIMEOUT_S // 60} minutes"
            raise DecodeError(f"{source.name}: couldn't read audio: {detail}")
    if not samples.dtype.isnative:                      # ffmpeg wrote little-endian; this host isn't
        samples = samples.astype(np.float32)
    return np.clip(samples, -1.0, 1.0, out=samples)


def _read_f32(pipe, capacity: int) -> np.ndarray:
    """Little-endian float32 samples from ``pipe`` into one array, grown and finally trimmed in place
    (``ndarray.resize`` reallocates, which moves no pages for an allocation this size)."""
    buf = np.empty(max(capacity, SAMPLE_RATE) * 4, dtype=np.uint8)
    filled = 0
    while True:
        if filled == buf.size:
            buf.resize(max(buf.size + 4 * SAMPLE_RATE, min(buf.size * 2, 4 * (MAX_SECONDS + 1) * SAMPLE_RATE)),
                       refcheck=False)
        with memoryview(buf) as whole, whole[filled:filled + READ_BYTES] as window:
            got = pipe.readinto(window)
        if not got:
            break
        filled += got
    buf.resize(filled - filled % 4, refcheck=False)
    return buf.view("<f4")


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
