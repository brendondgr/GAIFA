"""NVIDIA GPUs (plan 35.1): `nvidia-smi` for the name, memory, compute capability and driver."""

from __future__ import annotations

from dataclasses import dataclass

from .linux import PciGpu
from .model import Gpu
from .source import Source, first_match

QUERY = ["--query-gpu=index,pci.bus_id,name,memory.total,compute_cap,driver_version", "--format=csv,noheader,nounits"]
WSL_SMI = "/usr/lib/wsl/lib/nvidia-smi"


@dataclass
class SmiRow:
    index: int
    bus: str          # 01:00.0 (the part after the domain, lower case)
    name: str
    mib: int          # 0 when nvidia-smi says [N/A] (a GPU that shares the system's memory)
    cc: str           # 8.9
    driver: str


def smi_path(src: Source) -> str | None:
    return src.which("nvidia-smi") or (WSL_SMI if "nvidia-smi" in (src.ls("/usr/lib/wsl/lib") or []) else None)


def smi(src: Source) -> tuple[list[SmiRow], str]:
    """Every GPU nvidia-smi reports, and the CUDA version its driver supports ("" if it doesn't answer)."""
    exe = smi_path(src)
    if not exe:
        return [], ""
    rows = []
    for line in (src.run([exe, *QUERY]) or "").splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 6 or not parts[0].isdigit():
            continue
        bus = parts[1].lower().split(":", 1)[-1] if ":" in parts[1] else parts[1].lower()
        rows.append(SmiRow(int(parts[0]), bus, parts[2], int(parts[3]) if parts[3].isdigit() else 0, parts[4], parts[5]))
    cuda = first_match(r"CUDA Version:\s*([\d.]+)", src.run([exe])) or ""
    return rows, cuda


def from_row(row: SmiRow, cuda: str, vulkan: bool) -> Gpu:
    g = Gpu(vendor="nvidia", name=row.name if row.name.startswith("NVIDIA") else f"NVIDIA {row.name}",
            memory="dedicated" if row.mib else "unified", vram_bytes=row.mib * 2**20, driver=row.driver)
    if row.cc and row.cc != "[N/A]":
        g.arch = "sm_" + row.cc.replace(".", "")
    if cuda:
        g.runtimes["cuda"] = cuda
        g.accels.append("cuda")
    if vulkan:
        g.runtimes["vulkan"] = "yes"
        g.accels.append("vulkan")
    return g


def gpu(src: Source, dev: PciGpu, rows: list[SmiRow], cuda: str, vulkan: bool) -> Gpu:
    bus = dev.addr.lower().split(":", 1)[-1]
    row = next((r for r in rows if r.bus == bus), None)
    if row is None:
        g = Gpu(vendor="nvidia", name=f"NVIDIA GPU {dev.device_id}", driver=dev.driver, pci=dev.addr)
        g.problems.append("the NVIDIA driver doesn't answer (nvidia-smi is missing or fails): CUDA can't be used"
                          + (" — the open-source nouveau driver is loaded instead" if dev.driver == "nouveau" else ""))
        return g
    g = from_row(row, cuda, vulkan)
    g.pci, g.driver = dev.addr, row.driver
    return g
