"""A throwaway lcpp home: data/ with fixture JSON, tiny stand-in GGUF files.

Nothing here touches the real data/ directory, the real models, systemd, or
the real relay.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lcpp.paths import Paths

SETTINGS = {
    "daemon": {"port": 7700},
    "llama": {
        "binary": "runtime/llama.cpp/bin/current/llama-server",
        "environment": {"AMD_VULKAN_ICD": "RADV"},
        "server_params": {"jinja": True, "reasoning": "auto", "reasoning-budget": -1},
    },
    "ports": {"start": 17071, "end": 17099},
    "relay": {"url": "http://127.0.0.1:4000", "dashboard_url": "http://127.0.0.1:4000/",
              "auto_register": False},
    "scan_dirs": ["models", "extra"],
}

MODELS = {
    "defaults": {"ctx-size": 262144, "cache-type-k": "q8_0", "cache-type-v": "q8_0",
                 "n-gpu-layers": 999, "flash-attn": True, "no-mmap": False},
    "models": {
        "gemma-4-26B-it": {
            "nicknames": ["gemma4-26B"], "path": "models/Gemma4-26B/g26.gguf",
            "mmproj": "models/Gemma4-26B/mmproj-g26.gguf",
            "draft": "models/Gemma4-26B/mtp-g26.gguf", "spec_type": "draft-mtp",
            "params": {"gpu-layers-draft": 999},
        },
        "gemma-4-19B-it": {"nicknames": ["gemma4-19B"], "path": "models/Gemma4-19B/g19.gguf"},
        "minicpm-5-2B": {"nicknames": ["MiniCPM5-2B"], "path": "models/MiniCPM5-2B/mini.gguf",
                         "params": {"ctx-size": 131072}},
        "big-split": {"nicknames": ["bigsplit"], "path": "extra/Big/Big-00001-of-00003.gguf"},
    },
}

FILES = {
    "models/Gemma4-26B/g26.gguf": 2000,
    "models/Gemma4-26B/mmproj-g26.gguf": 300,
    "models/Gemma4-26B/mtp-g26.gguf": 100,
    "models/Gemma4-19B/g19.gguf": 1500,
    "models/MiniCPM5-2B/mini.gguf": 400,
    "extra/Big/Big-00001-of-00003.gguf": 10,
    "extra/Big/Big-00002-of-00003.gguf": 5000,
    "extra/Big/Big-00003-of-00003.gguf": 4000,
    "extra/Loose-12B-Q4_K_M.gguf": 700,
    "models/New/fresh-7B-Q8_0.gguf": 800,
}


@pytest.fixture
def home(tmp_path: Path) -> Paths:
    root = tmp_path / "lcpp"
    (root / "data").mkdir(parents=True)
    (root / "data/lcpp.json").write_text(json.dumps(SETTINGS))
    (root / "data/models.json").write_text(json.dumps(MODELS))
    for rel, size in FILES.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"\0" * size)
    return Paths(root=root, state=tmp_path / "state")
