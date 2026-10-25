"""The mod's settings, from the environment GAIFA sets (service.toml [run.env], architecture §4.4)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent       # services/embed

MODEL_ID = "embeddinggemma-2"
REPO = "google/embeddinggemma-2"
REVISION = "914f7f89142e33e77833254d9c9b90c3cef7303b"   # what install.sh downloads (2026-10-06)


@dataclass
class Settings:
    port: int = 5104
    model_dir: Path = HERE / "data" / MODEL_ID
    state_dir: Path = HERE / "data" / "state"
    hub_url: str | None = None
    device: str = "auto"              # auto (the GPU when torch sees one) | cuda | cpu
    idle_unload_s: float = 300.0      # 0 = never
    max_inputs: int = 256             # per request
    audio_max_s: float = 320.0        # 25 tokens a second in an 8k context
    video_max_frames: int = 32        # the processor's own cap; longer videos are sampled below 1 fps
    batch_text: int = 32
    batch_media: int = 4
    # the library (plan 28.2)
    databases: Path = HERE / "data"
    index: bool = True                # follow the hub's outputs and index them (each batch waits for the GPU slot, plan 31.3)
    index_audio_max_s: float = 3600.0 # longer audio is indexed up to here (30 s windows)
    index_batch_text: int = 8         # chunks of ~800 tokens a batch (32 of them peaked at 7.5 GB)

    @classmethod
    def from_env(cls, port: int | None = None) -> "Settings":
        e = os.environ
        d = cls()
        return cls(
            port=port or int(e.get("GAIFA_PORT", d.port)),
            model_dir=Path(e.get("EMBED_MODEL_DIR", d.model_dir)),
            state_dir=Path(e.get("EMBED_STATE_DIR", d.state_dir)),
            hub_url=(e.get("GAIFA_URL") or "").rstrip("/") or None,
            device=e.get("EMBED_DEVICE", d.device),
            idle_unload_s=float(e.get("EMBED_IDLE_UNLOAD_S") or e.get("GAIFA_IDLE_UNLOAD_S") or d.idle_unload_s),
            max_inputs=int(e.get("EMBED_MAX_INPUTS", d.max_inputs)),
            audio_max_s=float(e.get("EMBED_AUDIO_MAX_S", d.audio_max_s)),
            batch_text=int(e.get("EMBED_BATCH_TEXT", d.batch_text)),
            batch_media=int(e.get("EMBED_BATCH_MEDIA", d.batch_media)),
            databases=Path(e.get("GAIFA_DATABASES", d.databases)),
            index=e.get("EMBED_INDEX", "1") not in ("", "0", "false", "no"),
            index_audio_max_s=float(e.get("EMBED_INDEX_AUDIO_MAX_S", d.index_audio_max_s)),
            index_batch_text=int(e.get("EMBED_INDEX_BATCH_TEXT", d.index_batch_text)),
        )
