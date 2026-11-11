"""Audio for the tests and reading the bridge's events."""

from __future__ import annotations

import json

import numpy as np

RATE = 16000


def tone(seconds: float, level: float = 0.3, rate: int = RATE) -> bytes:
    """A loud warbling tone: speech to the loudness gate."""
    t = np.arange(int(seconds * rate)) / rate
    x = level * np.sin(2 * np.pi * 220 * t) * (0.6 + 0.4 * np.sin(2 * np.pi * 5 * t))
    return (x * 32767).astype(np.int16).tobytes()


def quiet(seconds: float, rate: int = RATE) -> bytes:
    rng = np.random.default_rng(1)
    return (rng.normal(0, 20, int(seconds * rate))).astype(np.int16).tobytes()


def chunks(pcm: bytes, ms: int = 100, rate: int = RATE):
    step = rate * 2 * ms // 1000
    for i in range(0, len(pcm), step):
        yield pcm[i:i + step]


def say(ws, speech_s: float = 0.6, quiet_s: float = 0.7) -> None:
    for c in chunks(tone(speech_s) + quiet(quiet_s)):
        ws.send_bytes(c)


def until(ws, type_: str, limit: int = 400) -> tuple[dict, list[dict], int]:
    """Read until an event of `type_`: (it, the events before it, the audio bytes received meanwhile)."""
    seen: list[dict] = []
    audio = 0
    for _ in range(limit):
        msg = ws.receive()
        if msg.get("bytes") is not None:
            audio += len(msg["bytes"])
            continue
        if msg.get("type") == "websocket.close":
            raise AssertionError(f"closed ({msg.get('code')}) before {type_}: {seen}")
        ev = json.loads(msg["text"])
        if ev["type"] == type_:
            return ev, seen, audio
        seen.append(ev)
    raise AssertionError(f"no {type_} in {limit} messages: {seen}")
