"""The adapter's settings, from the environment AIHub sets (service.toml [run.env], architecture §4.4)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent       # services/vllm


@dataclass
class Settings:
    port: int = 5101
    image: str = "docker.io/kyuz0/vllm-therock-gfx1151:latest"
    engine_port: int = 7801
    state_dir: Path = HERE / "data"
    hf_home: Path = HERE / "data" / "hf"
    profiles_dir: Path = HERE / "profiles"
    hub_url: str | None = None
    relay_url: str = "http://127.0.0.1:4000"
    podman: str = "podman"
    fake: bool = False
    start_timeout_s: float = 1200.0       # a first start compiles kernels for minutes
    overhead_gb: float = 6.0              # beyond vLLM's own budget: measured 4.2 GB (0.6B), 6.4 GB (35B-A3B)

    @property
    def cache_dir(self) -> Path:
        return self.state_dir / "cache"

    @property
    def site_dir(self) -> Path:
        """engine_site/: the sitecustomize every Python in the engine container loads."""
        return HERE / "engine_site"

    @classmethod
    def from_env(cls, port: int | None = None) -> "Settings":
        e = os.environ
        d = cls()
        return cls(
            port=port or int(e.get("AIHUB_PORT", d.port)),
            image=e.get("VLLM_IMAGE", d.image),
            engine_port=int(e.get("VLLM_ENGINE_PORT", d.engine_port)),
            state_dir=Path(e.get("VLLM_STATE_DIR", d.state_dir)),
            hf_home=Path(e.get("HF_HOME", d.hf_home)),
            profiles_dir=Path(e.get("VLLM_PROFILES_DIR", d.profiles_dir)),
            hub_url=(e.get("AIHUB_URL") or "").rstrip("/") or None,
            relay_url=e.get("VLLM_RELAY_URL", d.relay_url).rstrip("/"),
            podman=e.get("VLLM_PODMAN", d.podman),
            fake=e.get("VLLM_FAKE", "") not in ("", "0", "false"),
            start_timeout_s=float(e.get("VLLM_START_TIMEOUT_S", d.start_timeout_s)),
            overhead_gb=float(e.get("VLLM_OVERHEAD_GB", d.overhead_gb)),
        )


def gtt_total_bytes() -> int:
    """The GPU's addressable memory: on Strix Halo that is the GTT (amdgpu.gttsize), which is what vLLM's
    --gpu-memory-utilization is a fraction of. Falls back to MemTotal."""
    best = 0
    for p in Path("/sys/class/drm").glob("card*/device/mem_info_gtt_total"):
        try:
            best = max(best, int(p.read_text().strip()))
        except (OSError, ValueError):
            pass
    if best:
        return best
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) * 1024
    except OSError:
        pass
    return 128 * 10**9
