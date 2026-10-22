"""Intel GPUs (plan 35.1): i915 or xe, integrated or Arc, and the compute runtime PyTorch's xpu needs."""

from __future__ import annotations

from . import osinfo
from .amd import pci_short
from .linux import PciGpu, num
from .model import Gpu
from .source import Source

IGPU_ADDR = "0000:00:02.0"      # Intel's integrated GPU always sits here


def compute_runtime(src: Source) -> tuple[str, list[str]]:
    """(Level Zero's version or "", problems): xpu needs the loader and Intel's GPU driver for it."""
    loader, driver = osinfo.libs(src, "libze_loader.so"), osinfo.libs(src, "libze_intel_gpu.so")
    if loader and driver:
        return osinfo.lib_version(loader), []
    missing = [n for n, have in (("libze_loader (Level Zero)", loader), ("libze_intel_gpu (Intel's compute runtime)", driver)) if not have]
    return "", [f"{' and '.join(missing)} not installed: PyTorch (xpu) and llama.cpp's SYCL build can't use the GPU"]


def gpu(src: Source, dev: PciGpu, vulkan: bool) -> Gpu:
    name = pci_short(src.pci_name(dev.vendor_id, dev.device_id))
    g = Gpu(vendor="intel", name=f"Intel {name}" if name else f"Intel GPU {dev.device_id}", driver=dev.driver, pci=dev.addr)
    if dev.addr == IGPU_ADDR:
        g.memory = "unified"
    else:
        g.memory = "dedicated"
        for card in dev.cards:          # i915 reports an Arc card's VRAM here; xe doesn't (0: unknown)
            g.vram_bytes = g.vram_bytes or num(src, f"/sys/class/drm/{card}/lmem_total_bytes")
    if dev.driver not in ("i915", "xe"):
        g.problems.append(f"neither i915 nor xe is bound to this GPU (driver: {dev.driver or 'none'})")
        return g
    g.arch = dev.driver
    ze, problems = compute_runtime(src)
    if ze:
        g.runtimes["level_zero"] = ze
        g.accels.append("xpu")
    g.problems += problems
    if vulkan:
        g.runtimes["vulkan"] = "yes"
        g.accels.append("vulkan")
    return g
