"""The mod's settings, from the environment GAIFA sets (service.toml [run.env], architecture §4.4)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent       # services/decide


@dataclass
class Settings:
    port: int = 5107
    models_dir: Path = HERE / "data" / "models"     # data/models/decide: one folder per decision model
    state_dir: Path = HERE / "data" / "state"
    hub_url: str | None = None
    default_model: str = "d3-lite"
    device: str = "auto"              # auto (the GPU when torch sees one) | cuda | cpu
    batch_size: int = 8               # questions per forward pass
    verify: str = "full"              # the d3 runtime's check of the files against their manifest: full | fast
    idle_unload_s: float = 300.0      # 0 = never
    max_questions: int = 32           # per request
    max_input_chars: int = 100_000

    @classmethod
    def from_env(cls, port: int | None = None) -> "Settings":
        e = os.environ
        d = cls()
        return cls(
            port=port or int(e.get("GAIFA_PORT", d.port)),
            models_dir=Path(e.get("DECIDE_MODELS_DIR", d.models_dir)),
            state_dir=Path(e.get("DECIDE_STATE_DIR", d.state_dir)),
            hub_url=(e.get("GAIFA_URL") or "").rstrip("/") or None,
            default_model=e.get("DECIDE_MODEL", d.default_model),
            device=e.get("DECIDE_DEVICE", d.device),
            batch_size=int(e.get("DECIDE_BATCH", d.batch_size)),
            verify=e.get("DECIDE_VERIFY", d.verify),
            idle_unload_s=float(e.get("DECIDE_IDLE_UNLOAD_S") or e.get("GAIFA_IDLE_UNLOAD_S") or d.idle_unload_s),
            max_questions=int(e.get("DECIDE_MAX_QUESTIONS", d.max_questions)),
        )
