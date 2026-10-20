"""The settings the ported engine reads, and the mod's own (environment).

The four models are the prototype's (`app/config/schema.py`), trimmed to what the ASR core, the
detectors and the streaming engine read. The mod's settings come from the environment that
`service.toml` sets, with defaults that work when it runs on its own.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

VadDetector = Literal["energy", "silero"]
ComputeDevice = Literal["auto", "cpu", "cuda"]
Precision = Literal["int8", "float16", "float32"]


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class VadConfig(_Base):
    """Voice activity detection, its hysteresis, and its pause threshold."""

    enabled: bool = True
    #: Silero: on real speech it found 83% of frames against energy's 62%, and on a tone fixture
    #: 1% against 62% (measured in the prototype). It ships inside faster-whisper.
    detector: VadDetector = "silero"
    model_path: str | None = None
    sensitivity: float = Field(default=0.6, ge=0.0, le=1.0)
    enter_frames: int = Field(default=3, ge=1, le=20)
    leave_frames: int = Field(default=10, ge=1, le=100)
    pause_ms: int = Field(default=500, ge=100, le=5000)


class HallucinationConfig(_Base):
    """Thresholds for discarding text the speech model invented rather than heard."""

    enabled: bool = True
    no_speech_threshold: float = Field(default=0.6, ge=0.0, le=1.0)
    logprob_threshold: float = Field(default=-1.0, ge=-10.0, le=0.0)
    #: Above this the model's no-speech estimate needs no corroboration (`tiny` invented "Oh" at
    #: 0.901 with a log-probability of -0.99 on a non-speech fixture).
    no_speech_certain: float = Field(default=0.85, ge=0.0, le=1.0)
    min_word_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    drop_phrases_enabled: bool = True
    max_phrase_seconds: float = Field(default=3.0, ge=0.5, le=30.0)


class AsrConfig(_Base):
    """Speech model selection."""

    backend: str = "faster-whisper"
    model: str = "small"
    device: ComputeDevice = "auto"
    precision: Precision = "float16"
    language: str | None = None
    beam_size: int = Field(default=1, ge=1, le=10)
    session_prompt: str = ""
    use_session_prompt: bool = True
    use_rolling_prompt: bool = True
    rolling_prompt_chars: int = Field(default=220, ge=0, le=2000)
    vad_filter: bool = True
    hallucination: HallucinationConfig = Field(default_factory=HallucinationConfig)
    #: Run a GPU model in a process of its own: a GPU memory fault aborts the process that made
    #: it, and isolated that costs a restarted worker rather than the server.
    process_isolation: bool = True
    #: The model's folder (``data/models/stt/<model>``), so nothing is fetched into ~/.cache.
    model_path: str | None = None
    #: Where faster-whisper downloads weights when ``model_path`` is not set (`download_root`).
    download_root: str | None = None


class StreamingConfig(_Base):
    """Buffer bounds, commit policy and trim behaviour of the live engine."""

    agreement_count: int = Field(default=2, ge=1, le=5)
    step_s: float = Field(default=0.75, ge=0.1, le=5.0)
    min_buffer_s: float = Field(default=1.0, ge=0.2, le=10.0)
    max_buffer_s: float = Field(default=25.0, ge=5.0, le=30.0)
    commit_timeout_s: float = Field(default=15.0, ge=2.0, le=120.0)
    retained_context_s: float = Field(default=0.75, ge=0.0, le=5.0)
    max_segment_s: float = Field(default=30.0, ge=5.0, le=120.0)
    repetition_limit: int = Field(default=3, ge=2, le=20)


MOD_DIR = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    """The mod's own settings, read from the environment once at start."""

    port: int
    outputs: Path
    models: Path
    hub_url: str
    backend: str
    device: str
    idle_unload_s: float

    @property
    def weights(self) -> Path:
        return self.models / "stt"

    @classmethod
    def from_env(cls) -> Settings:
        env = os.environ
        root = Path(env.get("AIHUB_ROOT") or MOD_DIR.parent.parent)
        return cls(
            port=int(env.get("AIHUB_PORT") or 5105),
            outputs=Path(env.get("AIHUB_OUTPUTS") or root / "outputs" / "stt"),
            models=Path(env.get("AIHUB_MODELS") or root / "data" / "models"),
            hub_url=env.get("AIHUB_URL") or "http://127.0.0.1:7000",
            backend=env.get("STT_BACKEND") or "faster-whisper",
            device=env.get("STT_DEVICE") or "auto",
            idle_unload_s=float(env.get("STT_IDLE_UNLOAD_S") or env.get("AIHUB_IDLE_UNLOAD_S") or 300),
        )
