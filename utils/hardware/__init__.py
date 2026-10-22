"""What this machine has (plan 35.1): the OS, WSL, the GPUs, their memory and runtimes, and the
accelerators AIHub can use here (`rocm`, `cuda`, `xpu`, `mps`, `vulkan`, `cpu`).

Standard library only: `aihub setup` and `aihub hardware` use it from a bare clone. Nothing runs at
import; `detect()` reads the machine once and caches it. `AIHUB_HARDWARE_FIXTURE=<snapshot.json>`
(dev only) makes it read a recorded machine instead.
"""

from __future__ import annotations

import json
import os
from typing import Any

from . import amd, apple, intel, linux, nvidia, osinfo, wsl
from .model import ACCELS, DEVICE, Gpu, Machine
from .source import Recorder, Snapshot, Source

__all__ = ["ACCELS", "DEVICE", "Gpu", "Machine", "Source", "detect", "detect_from", "from_snapshot", "record", "refresh"]

_cache: Machine | None = None


def _gpus_linux(src: Source) -> list[Gpu]:
    devs = linux.pci_gpus(src)
    vulkan = linux.vulkan_vendors(src)
    targets = amd.kfd_targets(src) if any(d.vendor == "amd" for d in devs) else []
    rows, cuda = nvidia.smi(src) if any(d.vendor == "nvidia" for d in devs) else ([], "")
    out = []
    for d in devs:
        if d.vendor == "amd":
            out.append(amd.gpu(src, d, targets, "amd" in vulkan))
        elif d.vendor == "nvidia":
            out.append(nvidia.gpu(src, d, rows, cuda, "nvidia" in vulkan))
        else:
            out.append(intel.gpu(src, d, "intel" in vulkan))
    return out


def detect_from(src: Source) -> Machine:
    """The machine as `src` shows it."""
    p = src.platform()
    system = p["system"]
    m = Machine(os=system, arch=p.get("machine", ""), kernel=p.get("release", ""), cpus=p.get("cpus", 0))
    m.ram_bytes = osinfo.ram_bytes(src, system)
    m.cpu = osinfo.cpu_name(src, system)
    m.pkg = osinfo.package_manager(src)
    if system == "darwin":
        m.distro = osinfo.darwin_release(src)
        m.gpus = apple.gpus(src, m.arch, m.ram_bytes)
    elif system == "linux":
        m.distro = osinfo.os_release(src)
        m.container = osinfo.container(src)
        m.wsl = wsl.is_wsl(src)
        m.gpus = wsl.gpus(src) if m.wsl else _gpus_linux(src)
    for g in m.gpus:
        if g.memory == "unified" and not g.vram_bytes:
            g.vram_bytes = m.ram_bytes          # an integrated GPU may address the system's memory
    # Dedicated GPUs first (the bigger the better), then integrated ones; number them.
    m.gpus.sort(key=lambda g: (g.memory != "dedicated", -g.vram_bytes))
    seen: dict[str, int] = {}
    for i, g in enumerate(m.gpus):
        g.index = i
        g.vendor_index = seen.get(g.vendor, 0)
        seen[g.vendor] = g.vendor_index + 1
    found = {a for g in m.gpus for a in g.accels}
    m.accels = [a for a in ACCELS if a in found and a != "cpu"] + ["cpu"]
    return m


def detect(refresh: bool = False) -> Machine:
    """This machine, read once (or a fixture, with AIHUB_HARDWARE_FIXTURE)."""
    global _cache
    if _cache is None or refresh:
        fixture = os.environ.get("AIHUB_HARDWARE_FIXTURE")
        _cache = from_snapshot(json.loads(open(fixture).read())) if fixture else detect_from(Source())
    return _cache


def refresh() -> Machine:
    return detect(refresh=True)


def record() -> tuple[Machine, dict[str, Any]]:
    """Detect the live machine and keep everything detection read: a snapshot that replays it."""
    rec = Recorder()
    return detect_from(rec), rec.data


def from_snapshot(data: dict[str, Any]) -> Machine:
    return detect_from(Snapshot(data))
