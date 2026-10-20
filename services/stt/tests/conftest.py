"""Shared fixtures: the prototype's WAVs, a settings object in a temporary root, the mock app."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
SEMINAR = FIXTURES / "seminar-speech-real.wav"     # 25 s of real speech
SILENT = FIXTURES / "silent-20s.wav"
ALTERNATING = FIXTURES / "alternating-20s.wav"      # synthetic speech-like bursts and gaps


def pytest_collection_modifyitems(config, items):
    if os.environ.get("STT_GPU_TESTS") == "1":
        return
    skip = pytest.mark.skip(reason="GPU test: set STT_GPU_TESTS=1 (the GPU is shared)")
    for item in items:
        if "gpu" in item.keywords:
            item.add_marker(skip)


@pytest.fixture
def settings(tmp_path):
    from stt.config import Settings

    return Settings(port=0, outputs=tmp_path / "outputs" / "stt", models=tmp_path / "models",
                    hub_url="http://127.0.0.1:9", backend="mock", device="cpu", idle_unload_s=0)


def wait_job(client, jid: str, timeout: float = 30.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = client.get(f"/v1/jobs/{jid}").json()
        if job["state"] in ("done", "failed", "cancelled"):
            return job
        time.sleep(0.05)
    raise AssertionError(f"job {jid} didn't finish: {job}")
