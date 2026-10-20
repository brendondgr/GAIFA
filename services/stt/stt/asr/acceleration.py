"""Two guards from the prototype's `acceleration.py`: the gfx1151 int8 crash and the kept wheel.

**The int8 guard.** On this machine (an AMD gfx1151 through ROCm) `small` at `int8` on the GPU does
not raise or fall back: it aborts the process with "Memory access fault by GPU node-1". `tiny` and
`base` at int8 are fine, and `small` at float16 is fine, so it is the combination that is refused,
before the load, because a GPU fault cannot be caught afterwards.

**The kept wheel.** PyPI's CTranslate2 is a CPU/CUDA build; the ROCm build comes from the project's
GitHub releases. `uv` puts the PyPI one back whenever it syncs the package, so the ROCm wheel is
kept in `runtime/wheels/` and reinstalled whenever the installed one did not come from it.

Neither imports the GPU stack: hardware is read from the filesystem.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

from ..config import MOD_DIR

logger = logging.getLogger(__name__)

KFD_NODE = Path("/dev/kfd")
DRM_DIR = Path("/sys/class/drm")
#: The release archive carrying the ROCm build, by CTranslate2 version.
ROCM_WHEEL_URL = "https://github.com/OpenNMT/CTranslate2/releases/download/v{version}/rocm-python-wheels-Linux.zip"
KEPT_WHEEL_DIR = MOD_DIR / "runtime" / "wheels"

#: Models small enough to have been measured working with int8 on a ROCm GPU here.
ROCM_INT8_SAFE_MODELS = frozenset({"tiny", "tiny.en", "base", "base.en"})
#: Set to "1" to load a combination this refuses, on hardware where it is not broken.
UNSAFE_OVERRIDE = "STT_ALLOW_UNSAFE_COMPUTE"
#: Set to "1" to leave the installed CTranslate2 alone.
REPAIR_OFF = "STT_NO_GPU_REPAIR"


def detect_hardware() -> str:
    """``cuda``, ``rocm`` or ``none``: what kind of GPU the kernel exposes."""
    if Path("/proc/driver/nvidia/version").exists():
        return "cuda"
    if KFD_NODE.exists():
        return "rocm"
    try:
        for card in DRM_DIR.glob("card*"):
            driver = card / "device" / "driver"
            if driver.exists() and driver.resolve().name == "amdgpu":
                return "rocm"
    except OSError:
        pass
    return "none"


def unsafe_combination(device: str, precision: str, model: str) -> str:
    """Why this (device, precision, model) must not be loaded here, or empty if it may be."""
    if os.environ.get(UNSAFE_OVERRIDE) == "1":
        return ""
    if precision != "int8" or device not in ("cuda", "auto"):
        return ""
    if detect_hardware() != "rocm":
        return ""
    if model.split("/")[-1].lower() in ROCM_INT8_SAFE_MODELS:
        return ""
    return (
        f"Loading {model} at int8 on an AMD GPU crashes the process with a GPU memory fault "
        "rather than failing cleanly, so it is refused here. Use float16 on the GPU, or int8 on "
        "the CPU."
    )


def repair_kept_wheel() -> str | None:
    """Reinstall the kept ROCm wheel when something has replaced it. Returns what it did, if anything.

    Fires only on an AMD machine, with a wheel matching the installed version and this Python kept
    on disk, and when the installed CTranslate2 did not come from it (`direct_url.json`), so it
    cannot loop.
    """
    if os.environ.get(REPAIR_OFF) == "1" or detect_hardware() != "rocm":
        return None
    version = installed_version()
    wheel = kept_wheel(version) if version else None
    if wheel is None or installed_from(wheel):
        return None
    uv = shutil.which("uv")
    if uv is None:
        return None
    logger.info("Restoring the ROCm build of CTranslate2 from %s", wheel)
    try:
        result = subprocess.run(  # noqa: S603 - fixed executable, our own wheel
            [uv, "pip", "install", "--quiet", "--reinstall", "--no-deps",
             "--python", sys.executable, str(wheel)],
            capture_output=True, text=True, timeout=300, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return f"Could not restore the ROCm build of CTranslate2: {exc}"
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()
        return f"Could not restore the ROCm build of CTranslate2 from {wheel.name}" + (
            f": {detail[-1]}" if detail else ".")
    return f"Restored the ROCm build of CTranslate2 from {wheel.name}."


def kept_wheel(version: str, folder: Path | None = None) -> Path | None:
    """A kept wheel matching this CTranslate2 version and this Python, if there is one."""
    tag = f"{sys.version_info.major}{sys.version_info.minor}"
    try:
        found = sorted((folder or KEPT_WHEEL_DIR).glob(f"ctranslate2-{version}-cp{tag}-cp{tag}-*.whl"))
    except OSError:
        return None
    return found[0] if found else None


def installed_version() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("ctranslate2")
    except PackageNotFoundError:
        return ""


def installed_from(wheel: Path) -> bool:
    """Whether the installed CTranslate2 came from ``wheel`` (an index install has no direct_url)."""
    from importlib.metadata import PackageNotFoundError, distribution

    try:
        raw = distribution("ctranslate2").read_text("direct_url.json")
    except (PackageNotFoundError, OSError):
        return False
    if not raw:
        return False
    try:
        return str(json.loads(raw).get("url", "")).endswith(wheel.name)
    except ValueError:
        return False
