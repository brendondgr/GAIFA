"""Shared fixtures: settings in a temporary folder with model files and the fake llama-server."""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

import pytest

os.environ.pop("GAIFA_URL", None)            # never the installed hub

FAKE = Path(__file__).parent / "fake_llama.py"


@pytest.fixture
def settings(tmp_path):
    from voice import config
    from voice.config import Settings

    models = tmp_path / "models" / "s2s"
    folder = models / config.MODEL
    folder.mkdir(parents=True)
    for name in (*config.QUANTS.values(), config.MMPROJ):
        (folder / name).write_bytes(b"gguf")
    launcher = tmp_path / "llama-server"
    launcher.write_text(f"#!/bin/sh\nexec {sys.executable} {FAKE} \"$@\"\n")
    launcher.chmod(launcher.stat().st_mode | stat.S_IXUSR)
    return Settings(port=0, models=models, hub_url="", llama_bin=launcher, quant="q4_k_m", gpu_layers=0,
                    idle_unload_s=0, vad_model=tmp_path / "no-vad.onnx")


@pytest.fixture
def engine(settings, tmp_path):
    from voice.engine import Engine
    from voice.hub import Hub

    return Engine(settings, Hub(""), log_dir=tmp_path / "logs")
