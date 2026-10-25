"""The GPU inside a container (plan 37.4; docs/mods.md "Containers"). The reference helper: a mod that runs
its engine in podman or docker keeps an identical copy of this file (mods never import the hub). Standard
library only.

    machine = hardware()                       # GET $GAIFA_URL/api/system/hardware (None without GAIFA)
    argv = [runtime(), "run", "--rm", *gpu_args(machine, runtime()), image, …]

`gpu_args` gives the flags that hand the machine's GPU to a container:
- AMD: `/dev/kfd` and `/dev/dri` with the caller's groups (podman `--group-add keep-groups`; docker adds
  `video` and `render`).
- NVIDIA: the Container Toolkit's CDI device under podman (`--device nvidia.com/gpu=all`, or the one GPU
  in `GAIFA_GPU_INDEX`), `--gpus` under docker.
- Intel: `/dev/dri`.
- WSL2 (AMD or Intel): `/dev/dxg` and the Windows driver libraries in `/usr/lib/wsl` (NVIDIA goes through
  CDI there too).
- macOS: nothing (containers there can't reach the GPU).
Where SELinux is enforcing, podman also gets `--security-opt label=disable`, so the devices can be opened.
`runtime()` is `GAIFA_CONTAINER_RUNTIME` (the hub's `[containers] runtime`), else podman, else docker.
"""

from __future__ import annotations

import json
import os
import shutil
import urllib.request
from pathlib import Path
from typing import Any

SELINUX = Path("/sys/fs/selinux/enforce")


def runtime() -> str:
    want = os.environ.get("GAIFA_CONTAINER_RUNTIME", "")
    if want in ("podman", "docker"):
        return want
    return "podman" if shutil.which("podman") or not shutil.which("docker") else "docker"


def hardware(url: str | None = None, timeout: float = 5.0) -> dict[str, Any] | None:
    """The hub's view of this machine, or None without GAIFA."""
    base = url or os.environ.get("GAIFA_URL")
    if not base:
        return None
    try:
        with urllib.request.urlopen(base.rstrip("/") + "/api/system/hardware", timeout=timeout) as r:
            return json.loads(r.read())
    except (OSError, ValueError):
        return None


def _selinux_enforcing() -> bool:
    try:
        return SELINUX.read_text().strip() == "1"
    except OSError:
        return False


def gpu_args(machine: dict[str, Any] | None, runtime: str = "podman", index: int | None = None, selinux: bool | None = None) -> list[str]:
    """Flags that give a container the machine's GPU (all of them, or GPU `index`, as `gaifa hardware`
    numbers them; default: `GAIFA_GPU_INDEX`)."""
    if not machine or machine.get("os") != "linux":
        return []
    if index is None and os.environ.get("GAIFA_GPU_INDEX", "").isdigit():
        index = int(os.environ["GAIFA_GPU_INDEX"])
    gpus = [g for g in machine.get("gpus", []) if set(g.get("accels", [])) & {"rocm", "cuda", "xpu"}]
    if index is not None:
        gpus = [g for g in gpus if g.get("index") == index] or gpus
    vendors = {g["vendor"] for g in gpus}
    podman = runtime == "podman"
    out: list[str] = []
    if "nvidia" in vendors:
        n = [g["vendor_index"] for g in gpus if g["vendor"] == "nvidia"]
        one = index is not None and len(n) == 1
        out += (["--device", f"nvidia.com/gpu={n[0] if one else 'all'}"] if podman else ["--gpus", f"device={n[0]}" if one else "all"])
    if machine.get("wsl"):
        if vendors - {"nvidia"}:
            out += ["--device", "/dev/dxg", "-v", "/usr/lib/wsl:/usr/lib/wsl:ro"]
    else:
        if "amd" in vendors:
            out += ["--device", "/dev/kfd", "--device", "/dev/dri"]
        elif "intel" in vendors:
            out += ["--device", "/dev/dri"]
        if vendors & {"amd", "intel"}:
            out += ["--group-add", "keep-groups"] if podman else ["--group-add", "video", "--group-add", "render"]
    if out and podman and (_selinux_enforcing() if selinux is None else selinux):
        out += ["--security-opt", "label=disable"]
    return out
