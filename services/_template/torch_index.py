"""The PyTorch wheel index for an accelerator (plan 38.4). The reference helper: mods that install PyTorch keep
an identical copy (mods never import the hub). Standard library only, and runnable from a shell:

    uv pip install --index-url "$(python torch_index.py "$GAIFA_ACCEL")" torch

- `cuda`: download.pytorch.org's cu130, cu128 or cu126 build, the newest the NVIDIA driver can run
  (nvidia-smi's "CUDA Version"; cu126 when it can't be read).
- `rocm`: AMD's TheRock nightly index for the GPU family (GAIFA_GPU_ARCH: gfx1151, gfx110X, gfx120X, …).
- `xpu`: download.pytorch.org's xpu build (Intel GPUs; needs Intel's compute runtime on the host).
- `mps`: PyPI (Apple Silicon's wheels include MPS); `cpu` and `vulkan` (no PyTorch backend): the CPU build.
The table follows services/tts/engines/probe.py, which the speech mod uses for the same choice.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys

PYPI = "https://pypi.org/simple"
CPU = "https://download.pytorch.org/whl/cpu"
XPU = "https://download.pytorch.org/whl/xpu"
ROCM_FAMILY = [  # AMD TheRock nightly indexes are per GPU family
    (r"gfx115[0-3]", None), (r"gfx110.", "gfx110X-all"), (r"gfx120.", "gfx120X-all"), (r"gfx103.", "gfx103X-all"),
    (r"gfx101.", "gfx101X-dgpu"), (r"gfx94.", "gfx94X-dcgpu"), (r"gfx950", "gfx950-dcgpu"), (r"gfx90[0-9a]", None),
]


def rocm_family(gfx: str) -> str | None:
    for pat, fam in ROCM_FAMILY:
        if re.fullmatch(pat, gfx):
            return fam or gfx
    return None


def cuda_flavour(driver_cuda: str | None) -> str:
    """The newest PyTorch CUDA build the driver can run ("12.8" → cu128); cu126 when unknown."""
    try:
        v = tuple(int(x) for x in (driver_cuda or "").split(".")[:2])
    except ValueError:
        v = ()
    for need, flav in (((13, 0), "cu130"), ((12, 8), "cu128"), ((12, 6), "cu126")):
        if v and v >= need:
            return flav
    return "cu126"


def driver_cuda() -> str | None:
    try:
        out = subprocess.run(["nvidia-smi"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r"CUDA Version:\s*([\d.]+)", out)
    return m.group(1) if m else None


def index(accel: str, gfx: str | None = None, cuda: str | None = None, darwin: bool | None = None) -> str:
    darwin = sys.platform == "darwin" if darwin is None else darwin
    if accel == "cuda":
        return f"https://download.pytorch.org/whl/{cuda_flavour(cuda if cuda is not None else driver_cuda())}"
    if accel == "rocm":
        fam = rocm_family(gfx or os.environ.get("GAIFA_GPU_ARCH", ""))
        if not fam:
            raise SystemExit(f"no PyTorch ROCm index is known for {gfx or os.environ.get('GAIFA_GPU_ARCH') or 'this GPU'}")
        return f"https://rocm.nightlies.amd.com/v2/{fam}/"
    if accel == "xpu":
        return XPU
    if accel == "mps" or darwin:
        return PYPI
    return CPU


if __name__ == "__main__":
    print(index(sys.argv[1] if len(sys.argv) > 1 else os.environ.get("GAIFA_ACCEL", "cpu")))
