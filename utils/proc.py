"""Memory, GPU, process and port facts read from /proc and /sys (plan 5.1, ported from lcpp's `proc.py`).

GPU memory is unified on this machine: a model's weights live in GTT/VRAM buffers that
don't show in a process's VmRSS (a loaded 26B model reports ~1 GB RSS). So a mod's
footprint is RSS plus the DRM memory its GPU clients hold, over every process in its
unit's cgroup (plus `extra_units` and `containers`), each DRM client counted once.

Everything here blocks (files, `systemctl`, `podman`): the sampler runs it in a thread.
"""

from __future__ import annotations

import fnmatch
import functools
import logging
import os
import re
import socket
import subprocess
from collections.abc import Iterable
from pathlib import Path

log = logging.getLogger("aihub.proc")

PROC = Path("/proc")
SYS = Path("/sys")
CGROUP_ROOT = Path("/sys/fs/cgroup")
LISTEN = "0A"
CMD_TIMEOUT_S = 5
DRM_MEM_RE = re.compile(r"^drm-memory-(gtt|vram):\s+(\d+)\s*KiB", re.MULTILINE)
DRM_CLIENT_RE = re.compile(r"^drm-client-id:\s+(\d+)", re.MULTILINE)


def _read(path: str | Path) -> str | None:
    try:
        return Path(path).read_text()
    except OSError:
        return None


# ---- system ------------------------------------------------------------------


def meminfo(proc: Path = PROC) -> dict[str, int]:
    """`total_bytes`, `used_bytes` (MemTotal − MemAvailable) and `available_bytes`."""
    fields: dict[str, int] = {}
    for line in (_read(proc / "meminfo") or "").splitlines():
        key, _, rest = line.partition(":")
        parts = rest.split()
        if parts and parts[0].isdigit():
            fields[key] = int(parts[0]) * 1024
    total, avail = fields.get("MemTotal", 0), fields.get("MemAvailable", 0)
    return {"total_bytes": total, "used_bytes": total - avail, "available_bytes": avail}


def _gpu_card(sys: Path = SYS) -> Path | None:
    for card in sorted((sys / "class/drm").glob("card[0-9]*")):
        if (card / "device/mem_info_gtt_total").exists():
            return card / "device"
    return None


@functools.cache
def _pci_name(vendor: str, device: str) -> str | None:
    """The device's name from hwdata's pci.ids (no lspci needed)."""
    ids = _read("/usr/share/hwdata/pci.ids")
    if not ids:
        return None
    in_vendor = False
    for line in ids.splitlines():
        if not line or line.startswith("#"):
            continue
        if not line.startswith("\t"):
            in_vendor = line.startswith(vendor + " ")
        elif in_vendor and line.startswith("\t" + device + " "):
            name = line.strip()[len(device):].strip()
            bracket = re.search(r"\[([^\]]+)\]", name)
            name = (bracket.group(1) if bracket else name).split(" / ")[-1]  # one id can cover several SKUs
            return f"AMD {name}" if vendor == "1002" else name
    return None


def gpu(sys: Path = SYS) -> dict[str, object] | None:
    """The brief's `Memory.gpu`: name plus VRAM and GTT totals and use (AMD sysfs), or None."""
    dev = _gpu_card(sys)
    if dev is None:
        return None

    def num(name: str) -> int:
        v = (_read(dev / name) or "").strip()
        return int(v) if v.isdigit() else 0

    vendor = (_read(dev / "vendor") or "").strip().removeprefix("0x")
    device = (_read(dev / "device") or "").strip().removeprefix("0x")
    return {
        "name": _pci_name(vendor, device) or f"GPU {vendor}:{device}",
        "vram_total_bytes": num("mem_info_vram_total"), "vram_used_bytes": num("mem_info_vram_used"),
        "gtt_total_bytes": num("mem_info_gtt_total"), "gtt_used_bytes": num("mem_info_gtt_used"),
    }


# ---- processes -----------------------------------------------------------------


def process_tree(pid: int, proc: Path = PROC) -> list[int]:
    """`pid` and every descendant that still exists."""
    out, stack, seen = [], [pid], set()
    while stack:
        p = stack.pop()
        if p in seen or not (proc / str(p)).exists():
            continue
        seen.add(p)
        out.append(p)
        for task in (proc / str(p) / "task").glob("*"):
            stack.extend(int(k) for k in (_read(task / "children") or "").split())
    return out


def rss_bytes(pid: int, proc: Path = PROC) -> int:
    for line in (_read(proc / str(pid) / "status") or "").splitlines():
        if line.startswith("VmRSS:"):
            return int(line.split()[1]) * 1024
    return 0


def pss_bytes(pid: int, proc: Path = PROC) -> int:
    """The process's proportional share of its memory (`Pss` in `smaps_rollup`): pages shared
    with other processes (forked workers, shared libraries) are split between them, so a sum
    over many processes counts each page once. Falls back to RSS when `smaps_rollup` can't be read."""
    for line in (_read(proc / str(pid) / "smaps_rollup") or "").splitlines():
        if line.startswith("Pss:"):
            return int(line.split()[1]) * 1024
    return rss_bytes(pid, proc)


def gpu_bytes(pid: int, seen: set[str] | None = None, proc: Path = PROC) -> int:
    """GTT + VRAM held by the process's DRM clients. A client already in `seen` (shared with
    another process, e.g. after a fork) isn't counted again."""
    seen = set() if seen is None else seen
    total = 0
    try:
        entries = list((proc / str(pid) / "fdinfo").iterdir())
    except OSError:
        return 0
    for f in entries:
        text = _read(f)
        if not text or "drm-client-id" not in text:
            continue
        cid = DRM_CLIENT_RE.search(text)
        if not cid or cid.group(1) in seen:
            continue
        seen.add(cid.group(1))
        total += sum(int(kib) * 1024 for _, kib in DRM_MEM_RE.findall(text))
    return total


def footprint(pids: Iterable[int], proc: Path = PROC) -> int:
    """PSS + GPU memory of these processes and all their descendants, each counted once.
    PSS rather than RSS: a mod with 30 forked compile workers would otherwise count the memory
    they share 30 times."""
    every: list[int] = []
    for pid in pids:
        every.extend(p for p in process_tree(pid, proc) if p not in every)
    seen: set[str] = set()
    return sum(pss_bytes(p, proc) + gpu_bytes(p, seen, proc) for p in every)


# ---- units and containers ---------------------------------------------------------


def _cmd(*args: str) -> str | None:
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=CMD_TIMEOUT_S, check=False)
    except (OSError, subprocess.TimeoutExpired) as e:
        log.debug("%s: %s", args[0], e)
        return None
    return r.stdout if r.returncode == 0 else None


def unit_cgroup(unit: str) -> str | None:
    """A user unit's cgroup path (`ControlGroup`), or None if it isn't running."""
    out = (_cmd("systemctl", "--user", "show", unit, "-p", "ControlGroup", "--value") or "").strip()
    return out or None


def cgroup_pids(cgroup: str, root: Path = CGROUP_ROOT) -> list[int]:
    """Every process in the cgroup and its sub-cgroups."""
    base = root / cgroup.lstrip("/")
    pids: list[int] = []
    for dirpath, _, files in os.walk(base):
        if "cgroup.procs" in files:
            pids += [int(x) for x in (_read(Path(dirpath) / "cgroup.procs") or "").split() if x.isdigit()]
    return pids


def unit_pids(unit: str) -> list[int]:
    cg = unit_cgroup(unit)
    return cgroup_pids(cg) if cg else []


def units_matching(pattern: str) -> list[str]:
    """Running user units whose names match a glob (`lcpp-*.service`)."""
    out = _cmd("systemctl", "--user", "list-units", "--plain", "--no-legend", "--state=active", pattern) or ""
    names = [line.split()[0] for line in out.splitlines() if line.split()]
    return [n for n in names if fnmatch.fnmatch(n, pattern)]


def container_pid(name: str) -> int | None:
    """The main pid of a running podman container (its process tree is the container)."""
    out = (_cmd("podman", "inspect", "--format", "{{.State.Pid}}", name) or "").strip()
    return int(out) if out.isdigit() and out != "0" else None


def port_listening(port: int, timeout: float = 0.5) -> bool:
    """True when something accepts connections on 127.0.0.1:<port> (or [::1]:<port>)."""
    for family, host in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
        try:
            with socket.socket(family, socket.SOCK_STREAM) as s:
                s.settimeout(timeout)
                if s.connect_ex((host, port)) == 0:
                    return True
        except OSError:
            continue
    return False


def _listen_inodes(port: int) -> set[str]:
    inodes: set[str] = set()
    for table in ("tcp", "tcp6"):
        try:
            lines = (PROC / "net" / table).read_text().splitlines()[1:]
        except OSError:
            continue
        for line in lines:
            f = line.split()
            if len(f) > 9 and f[3] == LISTEN and int(f[1].rsplit(":", 1)[1], 16) == port:
                inodes.add(f[9])
    return inodes


def port_owner(port: int) -> dict[str, object] | None:
    """`{pid, name, cmdline}` of the process listening on `port`, or None if unknown.

    Only processes this user can inspect are found; for others the socket is
    seen but the owner isn't, and `{"pid": None, "name": "another user's process"}` is returned.
    """
    inodes = _listen_inodes(port)
    if not inodes:
        return None
    targets = {f"socket:[{i}]" for i in inodes}
    for pid_dir in PROC.iterdir():
        if not pid_dir.name.isdigit():
            continue
        try:
            for fd in os.scandir(pid_dir / "fd"):
                try:
                    if os.readlink(fd.path) in targets:
                        return describe(int(pid_dir.name))
                except OSError:
                    continue
        except OSError:
            continue
    return {"pid": None, "name": "another user's process", "cmdline": ""}


def describe(pid: int) -> dict[str, object]:
    try:
        name = (PROC / str(pid) / "comm").read_text().strip()
    except OSError:
        name = "?"
    try:
        cmdline = (PROC / str(pid) / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace").strip()
    except OSError:
        cmdline = ""
    return {"pid": pid, "name": name, "cmdline": cmdline}


def owner_text(owner: dict[str, object] | None) -> str:
    if not owner:
        return "another process"
    if owner.get("pid") is None:
        return str(owner.get("name"))
    cmd = str(owner.get("cmdline") or "")
    return f"{owner['name']} (pid {owner['pid']}{': ' + cmd[:120] if cmd else ''})"
