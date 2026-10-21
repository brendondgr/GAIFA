"""`aihub setup host` (plan 23.9): the checks from docs/setup/host.md, each with its fix.

Standard library only. Nothing here changes the machine: a fix is a command for the person (or
their agent) to run, and fixes that need root are marked so the wizard never runs them.
"""

from __future__ import annotations

import grp
import os
import pwd
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

GTT_MIB, PAGES = "131072", "33554432"     # host.md §1: 128 GiB
GPU_PARAMS = f"amdgpu.gttsize={GTT_MIB} ttm.pages_limit={PAGES}"
INSTALLERS = {                             # command → an installer that needs no root (host.md §3, the mods' setup docs)
    "uv": "curl -LsSf https://astral.sh/uv/install.sh | sh",
    "opencode": "curl -fsSL https://opencode.ai/install | bash -s -- --no-modify-path   (services/opencode/setup/opencode.md)",
    "blender": "Blender from blender.org, unpacked and linked into ~/.local/bin (host.md §3)",
}
PACKAGES = {                               # command → the Fedora package (host.md §3)
    "podman": "podman", "toolbox": "toolbox", "git": "git-core", "node": "nodejs22", "npm": "nodejs22-npm",
    "espeak-ng": "espeak-ng", "ffmpeg": "ffmpeg", "curl": "curl", "tar": "tar", "unzip": "unzip",
}


ADVICE = {"linger", "clone-under-home"}   # reported, never blocking a plan


@dataclass
class Check:
    id: str
    ok: bool
    detail: str
    fix: str = ""              # a command or an instruction; empty when ok
    needs_root: bool = False   # the wizard prints it and never runs it
    gpu: bool = False          # only matters to mods with gpu = true

    def dump(self) -> dict:
        return asdict(self)


class Probe:
    """The machine, read-only. Tests pass a fake with the same methods."""

    def cmdline(self) -> str:
        try:
            return Path("/proc/cmdline").read_text()
        except OSError:
            return ""

    def groups(self) -> set[str]:
        user = pwd.getpwuid(os.getuid()).pw_name
        names = {g.gr_name for g in grp.getgrall() if user in g.gr_mem}
        names.add(grp.getgrgid(os.getgid()).gr_name)
        return names

    def which(self, cmd: str) -> bool:
        return shutil.which(cmd) is not None

    def free_gb(self, path: Path) -> float:
        try:
            return shutil.disk_usage(path).free / 1e9
        except OSError:
            return 0.0

    def mem_bytes(self) -> int:
        try:
            for line in Path("/proc/meminfo").read_text().splitlines():
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) * 1024
        except (OSError, ValueError):
            pass
        return 0

    def gtt_bytes(self) -> int:
        for p in Path("/sys/class/drm").glob("card*/device/mem_info_gtt_total"):
            try:
                return int(p.read_text().strip())
            except (OSError, ValueError):
                continue
        return 0

    def linger(self) -> bool:
        try:
            out = subprocess.run(["loginctl", "show-user", os.environ.get("USER", ""), "-p", "Linger"],
                                 capture_output=True, text=True, timeout=5).stdout
        except (OSError, subprocess.TimeoutExpired):
            return False
        return out.strip() == "Linger=yes"


def checks(probe: Probe, root: Path, needs: set[str] = frozenset(), disk_gb: float = 0.0) -> list[Check]:
    """Every host check, in host.md's order. `needs` are the chosen mods' host commands, `disk_gb`
    what the plan will take."""
    out: list[Check] = []
    line = probe.cmdline()
    params = dict(p.split("=", 1) if "=" in p else (p, "") for p in line.split())
    missing = [k for k in ("amdgpu.gttsize", "ttm.pages_limit") if k not in params]
    out.append(Check("kernel-gtt", not missing, "the GPU may use most of the memory (GTT)" if not missing else f"{', '.join(missing)} not set",
                     "" if not missing else f'sudo grubby --update-kernel=ALL --args="{GPU_PARAMS}" && sudo reboot', needs_root=True, gpu=True))
    iommu_off = params.get("amd_iommu") == "off"
    out.append(Check("iommu-on", not iommu_off, "the IOMMU is on" if not iommu_off else "amd_iommu=off: nothing stops a stray GPU write (host.md §1)",
                     "" if not iommu_off else 'sudo grubby --update-kernel=ALL --remove-args="amd_iommu=off" && sudo reboot', needs_root=True, gpu=True))
    gtt, mem = probe.gtt_bytes(), probe.mem_bytes()
    enough = gtt >= 0.75 * mem if mem else gtt >= 96e9   # the default GTT is half the memory; host.md wants most of it
    out.append(Check("gtt-size", bool(gtt) and enough, f"GTT {gtt / 2**30:.1f} GiB of {mem / 2**30:.0f} GiB" if gtt else "no GPU memory reported (/sys/class/drm/card*/device/mem_info_gtt_total)",
                     "" if gtt and enough else "set the kernel parameters above and reboot; check with: cat /sys/class/drm/card*/device/mem_info_gtt_total", gpu=True))
    have = probe.groups()
    lacking = [g for g in ("video", "render") if g not in have]
    out.append(Check("gpu-groups", not lacking, "in the video and render groups" if not lacking else f"not in {', '.join(lacking)}",
                     "" if not lacking else "sudo usermod -aG video,render $USER  (then log out and in)", needs_root=True, gpu=True))
    out.append(Check("uv", probe.which("uv"), "uv is installed" if probe.which("uv") else "uv is missing",
                     "" if probe.which("uv") else INSTALLERS["uv"]))
    for cmd in sorted({"git", *needs} - {"uv"}):
        ok = probe.which(cmd)
        if cmd in INSTALLERS:
            fix, root_ = INSTALLERS[cmd], False
        else:
            pkg = PACKAGES.get(cmd, cmd)
            fix, root_ = f"sudo dnf install {pkg}", True
            if cmd == "ffmpeg":
                fix += "   (the full ffmpeg is in RPM Fusion: host.md §3)"
        out.append(Check(f"needs:{cmd}", ok, f"{cmd} is installed" if ok else f"{cmd} is missing", "" if ok else fix, needs_root=not ok and root_))
    home = Path.home()
    under = root.resolve().is_relative_to(home.resolve())
    out.append(Check("clone-under-home", under, "the clone is under your home folder" if under else f"the clone ({root}) isn't under {home}",
                     "" if under else "move the clone under your home folder: the ComfyUI toolbox only sees $HOME (host.md §5)", gpu=True))
    lin = probe.linger()
    out.append(Check("linger", lin, "lingering is on: AIHub keeps running after you log out" if lin else "lingering is off: the hub stops when you log out",
                     "" if lin else "loginctl enable-linger $USER"))
    free = probe.free_gb(root)
    out.append(Check("disk", free >= disk_gb, f"{free:.0f} GB free, {disk_gb:.1f} GB needed", "" if free >= disk_gb else "free some space, or choose fewer mods or models"))
    return out


def blocking(found: list[Check], gpu: bool) -> list[Check]:
    """The failed checks that stop a plan: GPU ones only when a chosen mod uses the GPU, and the
    disk; lingering is advice."""
    return [c for c in found if not c.ok and c.id not in ADVICE and (gpu or not c.gpu)]


def text(found: list[Check]) -> str:
    lines = []
    for c in found:
        mark = "ok  " if c.ok else ("root" if c.needs_root else "fix ")
        lines.append(f"{mark} {c.id:16} {c.detail}")
        if not c.ok and c.fix:
            lines.append(f"     {'':16} → {c.fix}")
    return "\n".join(lines)

