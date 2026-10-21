"""Settings, all overridable through the environment (see gen3d.env.example)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _path(name: str, default: str) -> Path:
    return Path(os.environ.get(name, default)).expanduser()


def _flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _device(name: str) -> str:
    return "cpu" if os.environ.get(name, "").strip().lower() == "cpu" else "gpu"


@dataclass(frozen=True)
class Settings:
    host: str = os.environ.get("GEN3D_HOST", "127.0.0.1")
    port: int = int(os.environ.get("GEN3D_PORT", "5050"))
    keep_alive_s: int = int(os.environ.get("GEN3D_KEEP_ALIVE_S", "330"))  # > any browser's idle pool
    data: Path = _path("GEN3D_DATA", str(ROOT / "data"))
    idle_unload_s: float = float(os.environ.get("GEN3D_IDLE_UNLOAD_S", "600"))  # 0 = never
    load_timeout_s: float = float(os.environ.get("GEN3D_LOAD_TIMEOUT_S", "600"))
    preload: bool = field(default_factory=lambda: _flag("GEN3D_PRELOAD"))
    fake_worker: bool = field(default_factory=lambda: _flag("GEN3D_FAKE_WORKER"))
    # The models: weights/, .venv/ (layered on the image's torch) and cube/ (upstream clone).
    cubeart: Path = _path("GEN3D_CUBEART", str(ROOT / "runtime" / "CubeArt"))
    # The image engines (plan 17): code clones and venvs next to CubeArt, built by scripts/install-runtime.sh.
    runtime: Path = _path("GEN3D_RUNTIME", str(ROOT / "runtime"))
    image: str = os.environ.get("GEN3D_IMAGE", "docker.io/kyuz0/amd-strix-halo-comfyui:latest")
    podman: str = os.environ.get("GEN3D_PODMAN", "podman")
    blender: str = os.path.expanduser(os.environ.get("GEN3D_BLENDER", "blender"))
    # Preview renders: gpu = Workbench on the GPU (OpenGL); cpu = the same under Mesa's llvmpipe, no GPU.
    preview_device: str = field(default_factory=lambda: _device("GEN3D_PREVIEW_DEVICE"))
    preview_max_faces: int = int(os.environ.get("GEN3D_PREVIEW_MAX_FACES", "300000"))  # 0 = never simplify
    preview_timeout_s: float = float(os.environ.get("GEN3D_PREVIEW_TIMEOUT_S", "180"))

    # Under AIHub: the database in data/databases, job folders in outputs/gen3d/<date>/, the
    # weights in data/models/3d. Standalone, all three default to the places they always were.
    db: str = os.environ.get("GEN3D_DB", "")
    outputs: str = os.environ.get("GEN3D_OUTPUTS", "")
    weights_dir: str = os.environ.get("GEN3D_WEIGHTS", "")

    @property
    def jobs_dir(self) -> Path:
        return Path(self.outputs).expanduser() if self.outputs else self.data / "jobs"

    @property
    def db_path(self) -> Path:
        return Path(self.db).expanduser() if self.db else self.data / "gen3d.db"

    @property
    def weights(self) -> Path:
        return Path(self.weights_dir).expanduser() if self.weights_dir else self.cubeart / "weights"


settings = Settings()
