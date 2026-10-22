"""GPUs on Linux's PCI bus, and the Vulkan drivers installed (plan 35.1)."""

from __future__ import annotations

from dataclasses import dataclass

from .source import Source

PCI = "/sys/bus/pci/devices"
VENDORS = {"0x1002": "amd", "0x10de": "nvidia", "0x8086": "intel"}
ICD_DIRS = ("/usr/share/vulkan/icd.d", "/etc/vulkan/icd.d")
ICD_VENDOR = {"radeon": "amd", "amd": "amd", "nvidia": "nvidia", "intel": "intel"}   # file name prefix → vendor (Mesa's dzn, lvp, nouveau… don't count)


@dataclass
class PciGpu:
    addr: str                # 0000:c4:00.0
    vendor: str              # amd | nvidia | intel
    vendor_id: str           # 1002
    device_id: str           # 1586
    driver: str              # amdgpu | nvidia | nouveau | i915 | xe | ""
    path: str                # /sys/bus/pci/devices/<addr>
    cards: list[str]         # drm card names (card1)


def pci_gpus(src: Source) -> list[PciGpu]:
    """Display controllers (PCI class 0x03…) from the three GPU vendors, in bus order."""
    out = []
    for addr in src.ls(PCI) or []:
        path = f"{PCI}/{addr}"
        cls = (src.read(f"{path}/class", 64) or "").strip()
        if not cls.startswith("0x03"):
            continue
        vid = (src.read(f"{path}/vendor", 64) or "").strip()
        if vid not in VENDORS:
            continue
        did = (src.read(f"{path}/device", 64) or "").strip()
        drv = (src.link(f"{path}/driver") or "").rsplit("/", 1)[-1]
        cards = [c for c in (src.ls(f"{path}/drm") or []) if c.startswith("card")]
        out.append(PciGpu(addr, VENDORS[vid], vid.removeprefix("0x"), did.removeprefix("0x"), drv, path, cards))
    return out


def vulkan_vendors(src: Source) -> set[str]:
    """Vendors with a Vulkan driver (ICD) installed."""
    found = set()
    for d in ICD_DIRS:
        for name in src.ls(d) or []:
            for prefix, vendor in ICD_VENDOR.items():
                if name.startswith(prefix):
                    found.add(vendor)
    return found


def num(src: Source, path: str) -> int:
    v = (src.read(path, 64) or "").strip()
    return int(v) if v.isdigit() else 0
