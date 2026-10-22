"""Which device a PyTorch mod uses (plan 38.4; docs/mods.md "Variants"). The reference helper: a mod keeps an
identical copy of this file (mods never import the hub). Standard library only; torch is imported only
when asked.

    import torch
    model.to(device())

`AIHUB_DEVICE` is set by the hub from the variant `aihub setup` installed (`[services.<id>] accel`): `cuda`
for CUDA and ROCm (ROCm's PyTorch answers as cuda), `xpu` for Intel, `mps` for Apple, `cpu`. Without it
(run by hand, or a mod set up before variants), the first that torch can reach: cuda, xpu, mps, cpu.
`MYMOD_DEVICE`-style overrides belong to the mod: pass one as `want`.
"""

from __future__ import annotations

import os

ORDER = ("cuda", "xpu", "mps", "cpu")


def available(name: str) -> bool:
    try:
        import torch
    except ImportError:
        return name == "cpu"
    if name == "cuda":
        return torch.cuda.is_available()
    if name == "xpu":
        return hasattr(torch, "xpu") and torch.xpu.is_available()
    if name == "mps":
        return hasattr(torch.backends, "mps") and torch.backends.mps.is_available()
    return name == "cpu"


def device(want: str | None = None) -> str:
    """`want` (if set and not "auto"), else AIHUB_DEVICE, else the first device torch can reach."""
    for choice in (want, os.environ.get("AIHUB_DEVICE")):
        if choice and choice != "auto":
            return choice
    return next(d for d in ORDER if available(d))
