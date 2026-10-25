"""Which variant of a setup this machine gets (plan 38.2). Standard library only.

A setup's variants (its doc's `[[variants]]`, or the one a version-2 block stands for) are tried in the
doc's order, its author's preference: the first whose `accel` this machine has (`utils/hardware`) and whose
`os` matches wins (lcpp lists its prebuilt Vulkan build before a CUDA build from source). With
`--accel <setup or mod>=<accel>` a person picks another. A setup with none that fits is "not available on
this machine" and is left out, with the reason. The chosen variant's steps, check and smoke replace the
block's where it has its own, and they run with its `env` plus `GAIFA_ACCEL` and `GAIFA_DEVICE`.
"""

from __future__ import annotations

import copy
from typing import Any

if __package__:
    from utils import hardware
else:
    import hardware  # type: ignore[no-redef]

LABEL = {"rocm": "ROCm", "cuda": "CUDA", "xpu": "Intel XPU", "mps": "Apple MPS", "vulkan": "Vulkan", "cpu": "CPU"}
OS_LABEL = {"linux": "Linux", "wsl": "WSL2", "darwin": "macOS"}


def machine_os(m: hardware.Machine) -> str:
    return "darwin" if m.os == "darwin" else "wsl" if m.wsl else "linux"


def overrides(items: list[str] | None) -> dict[str, str]:
    """`--accel tts=cpu` (repeatable) → {"tts": "cpu"}."""
    out: dict[str, str] = {}
    for item in items or []:
        key, _, accel = item.partition("=")
        if key.strip() and accel.strip():
            out[key.strip()] = accel.strip()
    return out


def pick(e: Any, m: hardware.Machine, want: str | None = None) -> tuple[Any | None, str]:
    """(the variant, "") or (None, why not)."""
    os_ = machine_os(m)
    variants = e.setup.effective_variants()
    if want:
        for v in variants:
            if v.accel == want and os_ in v.os:
                return v, ""
        return None, f"it has no {want} variant for {OS_LABEL[os_]}"
    for v in variants:
        if v.accel in m.accels and os_ in v.os:
            return v, ""
    here = [v for v in variants if os_ in v.os]
    if not here:
        return None, f"it doesn't run on {OS_LABEL[os_]} (only {', '.join(sorted({OS_LABEL[o] for v in variants for o in v.os}))})"
    return None, "it needs " + " or ".join(LABEL[v.accel] for v in here) + ", and this machine has " + ", ".join(LABEL[a] for a in m.accels)


def env_of(v: Any, m: hardware.Machine) -> dict[str, str]:
    """What the variant's steps, check and smoke run with."""
    arch = next((g.arch for g in m.gpus if v.accel in g.accels), "")
    return {**v.env, "GAIFA_ACCEL": v.accel, "GAIFA_DEVICE": hardware.DEVICE[v.accel], **({"GAIFA_GPU_ARCH": arch} if arch else {})}


def apply(e: Any, v: Any, m: hardware.Machine) -> Any:
    """A copy of the setup with the variant's own steps, check and smoke, and `run_env`, `variant`."""
    e = copy.copy(e)
    e.setup = copy.copy(e.setup)
    if v.steps is not None:
        e.setup.steps = list(v.steps)
    if v.check:
        e.setup.check = v.check
    if v.smoke:
        e.setup.smoke = v.smoke
    if v.needs is not None:
        e.setup.needs = list(v.needs)
    e.variant = v
    e.run_env = env_of(v, m)
    return e


def describe(e: Any, m: hardware.Machine) -> dict[str, Any]:
    v = e.variant
    os_ = machine_os(m)
    return {"setup": e.id, "mod": e.mod, "accel": v.accel, "label": LABEL[v.accel], "untested": os_ not in v.tested,
            "note": v.note or None, "env": dict(v.env)}


def choose(envs: list[Any], m: hardware.Machine, want: dict[str, str]) -> tuple[list[Any], list[dict[str, str]]]:
    """(the setups with their variants applied, [{setup, why}] for those this machine can't run)."""
    out, unavailable = [], []
    for e in envs:
        v, why = pick(e, m, want.get(e.id) or want.get(e.mod))
        if v is None:
            unavailable.append({"setup": e.id, "mod": e.mod, "why": why})
        else:
            out.append(apply(e, v, m))
    return out, unavailable


def mod_accels(envs: list[Any]) -> dict[str, str]:
    """One accel per mod for config.toml: its base setup's (the one named like the mod), else its first."""
    out: dict[str, str] = {}
    for e in sorted(envs, key=lambda e: (e.id != e.mod, e.id)):
        out.setdefault(e.mod, e.variant.accel)
    return out
