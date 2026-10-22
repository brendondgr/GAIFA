"""What detection finds (plan 35.1): the machine and its GPUs, as plain data."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

ACCELS = ("rocm", "cuda", "xpu", "mps", "vulkan", "cpu")   # the order a mod's variants are tried in
DEVICE = {"rocm": "cuda", "cuda": "cuda", "xpu": "xpu", "mps": "mps", "vulkan": "cpu", "cpu": "cpu"}   # → torch's device string


@dataclass
class Gpu:
    vendor: str                     # amd | nvidia | intel | apple
    name: str
    memory: str = "unknown"         # unified (shares the system's RAM) | dedicated (its own VRAM) | unknown
    vram_bytes: int = 0             # dedicated: its VRAM; unified: what it may address
    arch: str = ""                  # gfx1151, sm_89, m3, … ("" when unknown)
    driver: str = ""                # the kernel driver (amdgpu, nvidia, i915, xe) or its version
    pci: str = ""                   # 0000:c4:00.0 ("" under WSL and on macOS)
    index: int = 0                  # place in Machine.gpus
    vendor_index: int = 0           # place among this vendor's GPUs: CUDA_VISIBLE_DEVICES and the like count this way
    runtimes: dict[str, str] = field(default_factory=dict)   # rocm, cuda, level_zero, vulkan, metal → version or "yes"
    accels: list[str] = field(default_factory=list)          # what can run on it here
    problems: list[str] = field(default_factory=list)        # why an accel it could have isn't usable


@dataclass
class Machine:
    os: str                         # linux | darwin | windows
    arch: str                       # x86_64 | arm64 | …
    wsl: bool = False
    container: str = ""             # toolbox | podman | docker when this runs inside one
    distro: dict[str, str] = field(default_factory=dict)     # id, version, name, like
    kernel: str = ""
    cpu: str = ""
    cpus: int = 0
    ram_bytes: int = 0
    pkg: str = ""                   # dnf | apt | zypper | pacman | brew ("" when none is found)
    gpus: list[Gpu] = field(default_factory=list)
    accels: list[str] = field(default_factory=list)          # every accel usable here, best first; cpu last

    def compute_gpus(self) -> list[Gpu]:
        """GPUs with an accel beyond Vulkan (what a mod would pick a device among)."""
        return [g for g in self.gpus if set(g.accels) & {"rocm", "cuda", "xpu", "mps"}]

    def visible_env(self, index: int) -> dict[str, str]:
        """The variables that show a mod only GPU `index` (plan 36.3), counted the vendor's way."""
        g = next((x for x in self.gpus if x.index == index), None)
        if g is None:
            return {}
        env = {"AIHUB_GPU_INDEX": str(index)}
        n = str(g.vendor_index)
        if g.vendor == "nvidia":
            env["CUDA_VISIBLE_DEVICES"] = n
        elif g.vendor == "amd":
            env["HIP_VISIBLE_DEVICES"] = n
        elif g.vendor == "intel":
            env["ONEAPI_DEVICE_SELECTOR"] = f"level_zero:{n}"
            env["ZE_AFFINITY_MASK"] = n
        return env

    @property
    def unified(self) -> bool:
        """Every GPU shares the system's memory (one memory pool), or there's no GPU."""
        return all(g.memory != "dedicated" for g in self.gpus)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["unified"] = self.unified
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Machine:
        d = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        d["gpus"] = [Gpu(**{k: v for k, v in g.items() if k in Gpu.__dataclass_fields__}) for g in d.get("gpus", [])]
        return cls(**d)
