"""Apple Silicon (plan 35.1): the GPU shares the system's memory, and PyTorch reaches it as `mps`."""

from __future__ import annotations

import re

from .model import Gpu
from .source import Source


def gpus(src: Source, machine: str, ram: int) -> list[Gpu]:
    if machine not in ("arm64", "aarch64"):
        return []            # an Intel Mac: no GPU GAIFA can use
    brand = (src.run(["sysctl", "-n", "machdep.cpu.brand_string"]) or "").strip() or "Apple Silicon"
    m = re.search(r"Apple (M\d+)", brand)
    return [Gpu(vendor="apple", name=f"{brand} GPU", memory="unified", vram_bytes=ram, arch=m.group(1).lower() if m else "",
                runtimes={"metal": "yes"}, accels=["mps"])]
