"""Memory pools (plan 36.1): system RAM, and each dedicated GPU's VRAM as a budget of its own.

A machine whose GPUs all share the system's memory (this one, Apple Silicon, an integrated Intel
GPU) has one pool, `system`, and GPU memory counts against it, as before. Each dedicated GPU adds a
`gpu:<index>` pool (`utils.hardware.Gpu.index`):

- **NVIDIA:** totals and use from `nvidia-smi`; per process from `--query-compute-apps` (native
  Linux; WSL2 doesn't report processes).
- **AMD and Intel cards:** totals from sysfs (`mem_info_vram_*`; i915's `lmem_*`), per process from
  DRM fdinfo's `drm-memory-vram` by `drm-pdev`.
- Where a process's VRAM can't be read, a mod's share is unknown (0): the planner then counts what
  it acquired or its `vram_gb` estimate.

Blocking (commands, files): run in a thread.
"""

from __future__ import annotations

import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from utils import hardware, proc

SMI_TIMEOUT_S = 5
SYS_PCI = Path("/sys/bus/pci/devices")


@dataclass
class Pool:
    id: str                  # system | gpu:<index>
    name: str
    total_bytes: int
    used_bytes: int
    available_bytes: int

    def dump(self) -> dict[str, Any]:
        return asdict(self)


def pool_id(gpu: hardware.Gpu) -> str:
    return f"gpu:{gpu.index}"


def dedicated(machine: hardware.Machine) -> list[hardware.Gpu]:
    return [g for g in machine.gpus if g.memory == "dedicated"]


def _smi(args: list[str]) -> str:
    try:
        p = subprocess.run(["nvidia-smi", *args], capture_output=True, text=True, timeout=SMI_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError):
        return ""
    return p.stdout if p.returncode == 0 else ""


def _bus(s: str) -> str:
    """00000000:01:00.0 / 0000:01:00.0 → 01:00.0"""
    return s.strip().lower().split(":", 1)[-1] if s.count(":") >= 2 else s.strip().lower()


def _num(path: Path) -> int:
    try:
        v = path.read_text().strip()
    except OSError:
        return 0
    return int(v) if v.isdigit() else 0


class PoolReader:
    """The GPU pools of one machine, and each mod's share of them."""

    def __init__(self, machine: hardware.Machine, smi=_smi, sys_pci: Path = SYS_PCI, drm=proc.drm_vram_by_pdev, tree=proc.process_tree) -> None:
        self.machine, self.smi, self.sys_pci, self.drm, self.tree = machine, smi, sys_pci, drm, tree
        self.gpus = dedicated(machine)

    def read(self, pids: dict[str, list[int]]) -> tuple[list[Pool], dict[str, dict[str, int]]]:
        """(the GPU pools, {mod: {pool id: VRAM bytes}})."""
        if not self.gpus:
            return [], {}
        pools: list[Pool] = []
        use: dict[str, dict[str, int]] = {}
        nv = [g for g in self.gpus if g.vendor == "nvidia"]
        if nv:
            pools += self._nvidia(nv, pids, use)
        for g in self.gpus:
            if g.vendor == "nvidia":
                continue
            dev = self.sys_pci / g.pci if g.pci else None
            total = (_num(dev / "mem_info_vram_total") if dev else 0) or g.vram_bytes
            used = _num(dev / "mem_info_vram_used") if dev else 0
            if g.vendor == "intel" and dev and not used:
                avail = max((_num(c / "lmem_avail_bytes") for c in (dev / "drm").glob("card*")), default=0)
                used = max(0, total - avail) if avail else 0
            pools.append(Pool(pool_id(g), g.name, total, used, max(0, total - used)))
        by_pci = {g.pci: pool_id(g) for g in self.gpus if g.pci and g.vendor != "nvidia"}
        if by_pci:
            for sid, ps in pids.items():
                for pdev, n in self.drm(ps).items():
                    if pdev in by_pci:
                        use.setdefault(sid, {})[by_pci[pdev]] = use.get(sid, {}).get(by_pci[pdev], 0) + n
        return pools, use

    def _nvidia(self, gpus: list[hardware.Gpu], pids: dict[str, list[int]], use: dict[str, dict[str, int]]) -> list[Pool]:
        by_index = {g.vendor_index: g for g in gpus}
        by_bus = {_bus(g.pci): g for g in gpus if g.pci}
        pools = []
        for line in self.smi(["--query-gpu=index,memory.total,memory.used", "--format=csv,noheader,nounits"]).splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 3 or not parts[0].isdigit() or int(parts[0]) not in by_index:
                continue
            g = by_index[int(parts[0])]
            total = int(parts[1]) * 2**20 if parts[1].isdigit() else g.vram_bytes
            used = int(parts[2]) * 2**20 if parts[2].isdigit() else 0
            pools.append(Pool(pool_id(g), g.name, total, used, max(0, total - used)))
        if not pools:      # nvidia-smi didn't answer: the cards' sizes, use unknown
            pools = [Pool(pool_id(g), g.name, g.vram_bytes, 0, g.vram_bytes) for g in gpus]
        owner: dict[int, str] = {}
        for sid, ps in pids.items():
            for p in ps:
                for q in self.tree(p):
                    owner.setdefault(q, sid)
        for line in self.smi(["--query-compute-apps=pid,gpu_bus_id,used_memory", "--format=csv,noheader,nounits"]).splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 3 or not parts[0].isdigit() or not parts[2].isdigit():
                continue
            sid, g = owner.get(int(parts[0])), by_bus.get(_bus(parts[1])) or (gpus[0] if len(gpus) == 1 else None)
            if sid and g:
                pid_ = pool_id(g)
                use.setdefault(sid, {})[pid_] = use.get(sid, {}).get(pid_, 0) + int(parts[2]) * 2**20
        return pools

    def available(self, pool: str) -> int | None:
        """A pool's free bytes now (make-room waits poll it); None when it can't be read."""
        for p in self.read({})[0]:
            if p.id == pool:
                return p.available_bytes
        return None
