"""Streaming a recording to `WS /v1/stream` in real-time-sized frames, and comparing texts."""

from __future__ import annotations

import re

import numpy as np

FRAME_S = 0.1                       # what a browser's AudioWorklet batches send, roughly


def stream(client, samples: np.ndarray, *, encoding: str = "int16", **start) -> tuple[list[dict], dict]:
    """Send `samples` (16 kHz float32) through the stream; returns (events before done, done)."""
    events: list[dict] = []
    with client.websocket_connect("/v1/stream") as ws:
        ws.send_json({"type": "start", "encoding": encoding, **start})
        ready = ws.receive_json()
        assert ready["type"] == "ready", ready
        step = int(16_000 * FRAME_S)
        for i in range(0, samples.size, step):
            chunk = samples[i:i + step]
            data = (np.clip(chunk, -1, 1) * 32767).astype("<i2").tobytes() if encoding == "int16" \
                else chunk.astype("<f4").tobytes()
            ws.send_bytes(data)
        ws.send_json({"type": "stop"})
        while True:
            ev = ws.receive_json()
            if ev["type"] == "done":
                return events, ev
            events.append(ev)


def words(text: str) -> list[str]:
    return re.sub(r"[^a-z0-9' ]+", " ", text.lower().replace("-", " ")).split()


def wer(ref: str, hyp: str) -> float:
    """Word error rate of `hyp` against `ref` (Levenshtein over words / words in ref)."""
    r, h = words(ref), words(hyp)
    d = list(range(len(h) + 1))
    for i, rw in enumerate(r, 1):
        prev, d[0] = d[0], i
        for j, hw in enumerate(h, 1):
            prev, d[j] = d[j], min(d[j] + 1, d[j - 1] + 1, prev + (rw != hw))
    return d[len(h)] / max(1, len(r))
