"""Windows' GPUs as WSL2 sees them (plan 35.1): through /dev/dxg, with the vendor read from the
Windows driver store WSL mounts (no PCI bus here)."""

from __future__ import annotations

from . import intel, nvidia
from .model import Gpu
from .source import Source

DRIVERS = "/usr/lib/wsl/drivers"
STORE_VENDOR = (("nv", "nvidia"), ("iigd", "intel"), ("igd", "intel"), ("u0", "amd"), ("amd", "amd"))   # .inf folder prefix → vendor


def is_wsl(src: Source) -> bool:
    v = (src.read("/proc/version", 1024) or "").lower()
    return "microsoft" in v or "wsl" in v


def store_vendors(src: Source) -> list[str]:
    found: list[str] = []
    for name in src.ls(DRIVERS) or []:
        for prefix, vendor in STORE_VENDOR:
            if name.lower().startswith(prefix) and vendor not in found:
                found.append(vendor)
    return found


def gpus(src: Source) -> list[Gpu]:
    dxg = "dxg" in (src.ls("/dev") or [])
    vendors = store_vendors(src)
    rows, cuda = nvidia.smi(src)
    out: list[Gpu] = [nvidia.from_row(r, cuda, vulkan=False) for r in rows]
    if "nvidia" in vendors and not rows:
        g = Gpu(vendor="nvidia", name="NVIDIA GPU (through WSL)")
        g.problems.append("nvidia-smi doesn't answer in WSL: update the NVIDIA driver on Windows (WSL uses the Windows driver; don't install one inside Linux)")
        out.append(g)
    if "intel" in vendors:
        g = Gpu(vendor="intel", name="Intel GPU (through WSL)")
        ze, problems = intel.compute_runtime(src)
        if ze:
            g.runtimes["level_zero"] = ze
            g.accels.append("xpu")
        g.problems += problems
        out.append(g)
    if "amd" in vendors:
        g = Gpu(vendor="amd", name="AMD GPU (through WSL)")
        info = src.run(["rocminfo"]) if src.which("rocminfo") else None
        target = next((w for w in (info or "").split() if w.startswith("gfx") and w != "gfx000"), "")
        if target:
            g.arch = target
            g.accels.append("rocm")
        else:
            g.problems.append("ROCm on WSL supports only some Radeon cards, and rocminfo doesn't list this one: GAIFA uses the CPU here")
        out.append(g)
    if not dxg:
        for g in out:
            g.accels.clear()
            g.problems.append("no /dev/dxg: WSL's GPU support is off (update WSL with `wsl --update` and the Windows GPU driver)")
    return out
