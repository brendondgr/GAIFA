"""The mod's settings (environment, set by service.toml) and the model files it runs."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

MOD_DIR = Path(__file__).resolve().parent.parent

MODEL = "LFM3-Omni-2B"
MODEL_ID = "voice/lfm3-omni-2b"            # how a voice turn names its model in a chat
#: quant → the language model's file; the projector (vision, audio in, the codec) is the same for both.
QUANTS = {"q4_k_m": f"{MODEL}-Q4_K_M.gguf", "q8_0": f"{MODEL}-Q8_0.gguf"}
QUANT_LABELS = {"q4_k_m": "Q4_K_M", "q8_0": "Q8_0"}
MMPROJ = f"mmproj-{MODEL}-Q8_0.gguf"
REPO = "LiquidAI/LFM3-Omni-2B-GGUF"
VOICES = ("female", "male")
CONTEXT = 32768                            # the model's trained context
SLOTS = 3                                  # a conversation, its transcription session, one spare (/v1/speech)


@dataclass(frozen=True)
class Settings:
    port: int
    models: Path                           # …/data/models/s2s
    hub_url: str
    llama_bin: Path
    quant: str
    gpu_layers: int
    idle_unload_s: float
    vad_model: Path

    @property
    def folder(self) -> Path:
        return self.models / MODEL

    def model_path(self, quant: str) -> Path:
        return self.folder / QUANTS[quant]

    @property
    def mmproj_path(self) -> Path:
        return self.folder / MMPROJ

    @classmethod
    def from_env(cls) -> Settings:
        env = os.environ
        root = Path(env.get("GAIFA_ROOT") or MOD_DIR.parent.parent)
        quant = (env.get("VOICE_QUANT") or "q4_k_m").lower()
        return cls(
            port=int(env.get("GAIFA_PORT") or 5110),
            models=Path(env.get("VOICE_MODELS_DIR") or Path(env.get("GAIFA_MODELS") or root / "data" / "models") / "s2s"),
            hub_url=(env.get("GAIFA_URL") or "").rstrip("/"),
            llama_bin=Path(env.get("VOICE_LLAMA_BIN") or MOD_DIR / "runtime" / "llama.cpp" / "bin" / "current" / "llama-server"),
            quant=quant if quant in QUANTS else "q4_k_m",
            gpu_layers=int(env.get("VOICE_GPU_LAYERS") or 99),
            idle_unload_s=float(env.get("VOICE_IDLE_UNLOAD_S") or env.get("GAIFA_IDLE_UNLOAD_S") or 300),
            vad_model=Path(env.get("VOICE_VAD_MODEL") or MOD_DIR / "runtime" / "vad" / "silero_vad.onnx"),
        )
