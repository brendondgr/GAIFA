"""AMD GPUs (plan 35.1): amdgpu's sysfs, the KFD topology for the gfx target, ROCm and Vulkan."""

from __future__ import annotations

import re

from . import osinfo
from .linux import PciGpu, num
from .model import Gpu
from .source import Source

KFD = "/sys/class/kfd/kfd/topology/nodes"
# Chips whose GPU shares the system's memory (APUs): Strix Halo and Point, Phoenix, Rembrandt, Van Gogh, Renoir/Cezanne, Raven.
APU = re.compile(r"^gfx(115[0-3]|1103|103[5-7]|90c|902|909)$")
GIB = 2**30


def gfx(version: int) -> str:
    """KFD's gfx_target_version (110501) → the target name (gfx1151)."""
    return f"gfx{version // 10000}{(version // 100) % 100}{version % 100:x}"


def kfd_targets(src: Source) -> list[tuple[int, str]]:
    """(PCI device id, gfx target) for every GPU node KFD knows, in node order."""
    out = []
    for node in src.ls(KFD) or []:
        props = src.read(f"{KFD}/{node}/properties", 8192) or ""
        m = re.search(r"^gfx_target_version\s+(\d+)", props, re.M)
        if not m or not int(m.group(1)):
            continue
        d = re.search(r"^device_id\s+(\d+)", props, re.M)
        out.append((int(d.group(1)) if d else 0, gfx(int(m.group(1)))))
    return out


def pci_short(name: str | None) -> str | None:
    """pci.ids' "Strix Halo [Radeon 8060S / 8050S]" → "Radeon 8050S" (the bracket's last name)."""
    m = re.search(r"\[([^\]]+)\]", name or "")
    return m.group(1).split(" / ")[-1].strip() if m else name


def gpu(src: Source, dev: PciGpu, targets: list[tuple[int, str]], vulkan: bool) -> Gpu:
    name = pci_short(src.pci_name(dev.vendor_id, dev.device_id))
    g = Gpu(vendor="amd", name=f"AMD {name}" if name else f"AMD GPU {dev.device_id}", driver=dev.driver, pci=dev.addr)
    did = int(dev.device_id, 16) if dev.device_id else -1
    for i, (tid, target) in enumerate(targets):
        if tid == did:
            g.arch = target
            del targets[i]
            break
    vram, gtt = num(src, f"{dev.path}/mem_info_vram_total"), num(src, f"{dev.path}/mem_info_gtt_total")
    unified = bool(APU.match(g.arch)) or (0 < vram <= 2 * GIB < gtt)
    g.memory = "unified" if unified else ("dedicated" if vram else "unknown")
    g.vram_bytes = max(vram, gtt) if unified else vram
    if dev.driver != "amdgpu":
        g.problems.append(f"the amdgpu driver isn't bound to this GPU (driver: {dev.driver or 'none'})")
        return g
    hip = osinfo.libs(src, "libamdhip64.so")
    if hip:
        g.runtimes["rocm"] = osinfo.lib_version(hip)    # the host's ROCm (most mods bring their own)
    kfd = "kfd" in (src.ls("/dev") or [])    # listed, never opened (opening it starts a KFD process)
    if g.arch and kfd:
        g.accels.append("rocm")
    elif not kfd:
        g.problems.append("no /dev/kfd: ROCm can't reach the GPU")
    else:
        g.problems.append("KFD doesn't list this GPU's gfx target: ROCm can't use it")
    if vulkan:
        g.runtimes["vulkan"] = "yes"
        g.accels.append("vulkan")
    return g
