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
