"""Audio helpers: PCM -> container bytes, and normalising uploaded references with ffmpeg."""

from __future__ import annotations

import asyncio
import contextlib
import io
import shutil

import numpy as np
import soundfile as sf

MEDIA_TYPES = {
    "wav": "audio/wav",
    "flac": "audio/flac",
    "mp3": "audio/mpeg",
    "ogg": "audio/ogg",
    "pcm": "audio/pcm",
}
SF_FORMATS = {"wav": ("WAV", "PCM_16"), "flac": ("FLAC", "PCM_16"),
              "mp3": ("MP3", "MPEG_LAYER_III"), "ogg": ("OGG", "VORBIS")}


def encode(pcm: bytes, sample_rate: int, fmt: str) -> bytes:
    if fmt == "pcm":
        return pcm
    audio = np.frombuffer(pcm, dtype="<i2")
    buf = io.BytesIO()
    container, subtype = SF_FORMATS[fmt]
    # libsndfile's MP3 default is a very low VBR bitrate; 0.0 = best (160 kbps CBR at 24 kHz).
    extra = {"compression_level": 0.0, "bitrate_mode": "CONSTANT"} if fmt == "mp3" else {}
    sf.write(buf, audio, sample_rate, format=container, subtype=subtype, **extra)
    return buf.getvalue()


# Demuxers ffmpeg may use for an upload: audio and A/V containers that read only their own
# bytes. Playlists and concat lists (hls, concat, m3u...) are left out: an uploaded .m3u8 naming
# a local path made ffmpeg read that other file into the "reference".
DEMUXERS = "wav,w64,flac,mp3,ogg,mov,matroska,aac,aiff,caf,amr,asf,ac3,eac3,wv,ape,au,avi"
DECODE_TIMEOUT_S = 60.0


class TooLong(ValueError):
    """The audio runs past the caller's limit (decoding stopped there)."""


async def to_reference_wav(src: str, dst: str, sample_rate: int = 24_000, max_s: float = 60.0) -> None:
    """Any audio ffmpeg can read -> mono 16-bit WAV at the model rate, at most `max_s` seconds.

    Decoding stops just past `max_s` (a small FLAC of hours of silence otherwise unpacks to
    hundreds of MB) and raises TooLong; other failures raise ValueError.
    """
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg not found on PATH")
    proc = await asyncio.create_subprocess_exec(
        ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        "-protocol_whitelist", "file", "-format_whitelist", DEMUXERS, "-i", src,
        "-t", f"{max_s + 1:g}", "-vn", "-sn", "-dn",
        "-ac", "1", "-ar", str(sample_rate), "-sample_fmt", "s16", dst,
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, err = await asyncio.wait_for(proc.communicate(), DECODE_TIMEOUT_S)
    except BaseException as exc:   # timed out, or the request was cancelled: don't leave ffmpeg running
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
        await asyncio.shield(proc.wait())
        if isinstance(exc, TimeoutError):
            raise ValueError(f"decoding the audio took over {DECODE_TIMEOUT_S:.0f}s") from None
        raise
    if proc.returncode != 0:
        msg = err.decode(errors="replace").strip()
        if "not on whitelist" in msg:
            raise ValueError("not an audio file ffmpeg will open here (playlists and concat lists "
                             "are refused); send WAV, FLAC, MP3, OGG/Opus, M4A/MP4, WebM or similar")
        raise ValueError(f"could not decode the audio: {msg[-400:]}")
    if duration_s(dst) > max_s:
        raise TooLong(f"the audio is over {max_s:.0f}s")


def duration_s(path: str) -> float:
    return sf.info(path).duration
