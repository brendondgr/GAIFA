"""Live runs on the GPU (marked `gpu`; run with STT_GPU_TESTS=1). The GPU is shared: each test loads a
small model and unloads it when done. Weights come from data/models/stt (AIHUB_MODELS)."""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

import pytest
from conftest import SEMINAR

from stt import catalog
from stt.audio.decode import decode
from stt.batch.batch import transcribe_samples
from stt.config import MOD_DIR, Settings, VadConfig
from stt.engine import Engine
from stt.vad import build_detector

pytestmark = pytest.mark.gpu
MODELS = Path(os.environ.get("AIHUB_MODELS") or MOD_DIR.parent.parent / "data" / "models")


def gpu_settings() -> Settings:
    return Settings(port=0, outputs=Path("/nonexistent"), models=MODELS, hub_url="", backend="faster-whisper",
                    device="auto", idle_unload_s=0)


def test_small_on_the_gpu_transcribes_the_seminar_fast():
    if not catalog.is_downloaded(MODELS / "stt", "small"):
        pytest.skip("small isn't in data/models/stt")
    engine = Engine(gpu_settings())
    audio = decode(SEMINAR)

    async def run():
        await engine.ensure("small")
        try:
            assert engine.device == "cuda" and engine.precision == "float16"
            await asyncio.to_thread(engine.transcribe, audio[:16_000])           # warm
            started = time.monotonic()
            segs = await asyncio.to_thread(transcribe_samples, audio, transcribe=engine.transcribe,
                                           detector=build_detector(VadConfig()))
            return segs, time.monotonic() - started
        finally:
            await engine.unload()

    segs, took = asyncio.run(run())
    rtf = took / (audio.size / 16_000)
    print(f"\nsmall on the GPU: {audio.size / 16_000:.1f} s of audio in {took:.2f} s, real-time factor {rtf:.4f}")
    text = " ".join(s.text for s in segs).lower()
    assert "uncertainty relation" in text and "dense subspace" in text
    assert rtf < 0.25
    assert engine.state == "unloaded"


def test_the_live_stream_matches_the_file_route_on_real_speech(tmp_path):
    """29.2's check on the real model: the seminar streamed in 100 ms frames against the file route."""
    if not catalog.is_downloaded(MODELS / "stt", "small"):
        pytest.skip("small isn't in data/models/stt")
    from fastapi.testclient import TestClient
    from live_helpers import stream, wer
    from test_transcribe_files import LocalHub

    from conftest import wait_job
    from stt.server import create_app

    settings = Settings(port=0, outputs=tmp_path / "stt", models=MODELS, hub_url="", backend="faster-whisper",
                        device="auto", idle_unload_s=0)
    with TestClient(create_app(settings, hub=LocalHub({"seminar": SEMINAR}))) as client:
        job = wait_job(client, client.post("/v1/transcribe", json={"output_id": "output:seminar"}).json()["id"], 120)
        events, done = stream(client, decode(SEMINAR))
        client.post("/v1/unload")
    filed = job["result"]["text"]
    error = wer(filed, done["text"])
    print(f"\nfile:   {filed}\nstream: {done['text']}\nword error between them: {error:.3f}")
    assert sum(e["type"] == "committed" for e in events) >= 2
    assert error <= 0.15
