"""`gaifa setup host` (plan 23.9, 37.3): the checks from docs/setup/host*.md, each with its fix. The GPU
checks depend on the machine (`utils/hardware/`, cli_setup_gpu.py), package names on its package manager
(cli_setup_pkgs.py).

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

if __package__:
    from utils import cli_setup_gpu as gpu_mod
    from utils import cli_setup_pkgs as pkgs
    from utils import hardware
else:
    import cli_setup_gpu as gpu_mod  # type: ignore[no-redef]
    import cli_setup_pkgs as pkgs  # type: ignore[no-redef]
    import hardware  # type: ignore[no-redef]

INSTALLERS = {                             # command → an installer that needs no root (host.md §3, the mods' setup docs)
    "uv": "curl -LsSf https://astral.sh/uv/install.sh | sh",
    "opencode": "curl -fsSL https://opencode.ai/install | bash -s -- --no-modify-path   (services/opencode/setup/opencode.md)",
    "blender": "Blender from blender.org, unpacked and linked into ~/.local/bin (host.md §3)",
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

    def machine(self) -> hardware.Machine:
        return hardware.detect()

    def linger(self) -> bool:
        try:
            out = subprocess.run(["loginctl", "show-user", os.environ.get("USER", ""), "-p", "Linger"],
                                 capture_output=True, text=True, timeout=5).stdout
        except (OSError, subprocess.TimeoutExpired):
            return False
        return out.strip() == "Linger=yes"


def checks(probe: Probe, root: Path, needs: set[str] = frozenset(), disk_gb: float = 0.0) -> list[Check]:
    """Every host check, in host.md's order: the GPU's (for this machine), the tools, then lingering and
    disk. `needs` are the chosen mods' host commands, `disk_gb` what the plan will take."""
    m = probe.machine()
    out: list[Check] = gpu_mod.checks(probe, m, root, set(needs), Check)
    out.append(Check("uv", probe.which("uv"), "uv is installed" if probe.which("uv") else "uv is missing",
                     "" if probe.which("uv") else INSTALLERS["uv"]))
    for cmd in sorted({"git", *needs} - {"uv"}):
        ok = probe.which(cmd)
        if cmd in INSTALLERS:
            fix, root_ = INSTALLERS[cmd], False
        else:
            fix, root_ = pkgs.fix(cmd, m.pkg)
        out.append(Check(f"needs:{cmd}", ok, f"{cmd} is installed" if ok else f"{cmd} is missing", "" if ok else fix, needs_root=not ok and root_))
    if any(g.vendor == "amd" and g.memory == "unified" for g in m.gpus):     # the ComfyUI toolbox only sees $HOME
        home = Path.home()
        under = root.resolve().is_relative_to(home.resolve())
        out.append(Check("clone-under-home", under, "the clone is under your home folder" if under else f"the clone ({root}) isn't under {home}",
                         "" if under else "move the clone under your home folder: the ComfyUI toolbox only sees $HOME (host.md §5)", gpu=True))
    if m.os == "linux":
        lin = probe.linger()
        out.append(Check("linger", lin, "lingering is on: GAIFA keeps running after you log out" if lin else "lingering is off: the hub stops when you log out",
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

