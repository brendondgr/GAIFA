"""Memory, GPU and port facts read straight from /proc and /sys.

On this machine GPU memory is unified: a model's weights live in GTT/VRAM
buffers that do *not* show up in a process's VmRSS (a loaded 26B model
reports ~1 GB RSS). So an instance's footprint is RSS plus the DRM memory its
GPU clients hold, summed over the whole process tree (router mode spawns a
child llama-server per loaded model).
"""

from __future__ import annotations

import errno
import functools
import re
import socket
import subprocess
from pathlib import Path

DRM_MEM_RE = re.compile(r"^drm-memory-(gtt|vram):\s+(\d+)\s*KiB", re.MULTILINE)
DRM_CLIENT_RE = re.compile(r"^drm-client-id:\s+(\d+)", re.MULTILINE)
SS_USER_RE = re.compile(r'users:\(\("([^"]+)",pid=(\d+)')


def _read(path: str | Path) -> str | None:
    try:
        return Path(path).read_text()
    except OSError:
        return None


# ---- system ----------------------------------------------------------
def meminfo() -> dict[str, int]:
    fields: dict[str, int] = {}
    for line in (_read("/proc/meminfo") or "").splitlines():
        key, _, rest = line.partition(":")
        parts = rest.split()
        if parts:
            fields[key] = int(parts[0]) * 1024
    total = fields.get("MemTotal", 0)
    avail = fields.get("MemAvailable", 0)
    return {"total_bytes": total, "used_bytes": total - avail, "available_bytes": avail}


def _gpu_card() -> Path | None:
    for card in sorted(Path("/sys/class/drm").glob("card[0-9]*")):
        if (card / "device/mem_info_gtt_total").exists():
            return card / "device"
    return None


@functools.cache
def _pci_name(vendor: str, device: str) -> str | None:
    """Look the device up in hwdata's pci.ids (no lspci dependency)."""
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
            name = bracket.group(1) if bracket else name
            # One device id can cover several SKUs ("A / B / C"); the last is
            # the top part, which is the best guess without more probing.
            name = name.split(" / ")[-1]
            return f"AMD {name}" if vendor == "1002" else name
    return None


def gpu() -> dict[str, object] | None:
    dev = _gpu_card()
    if dev is None:
        return None

    def num(name: str) -> int:
        v = _read(dev / name)
        return int(v) if v and v.strip().isdigit() else 0

    vendor = (_read(dev / "vendor") or "").strip().removeprefix("0x")
    device = (_read(dev / "device") or "").strip().removeprefix("0x")
    name = _pci_name(vendor, device) or f"GPU {vendor}:{device}"
    return {
        "name": name,
        "vram_total_bytes": num("mem_info_vram_total"), "vram_used_bytes": num("mem_info_vram_used"),
        "gtt_total_bytes": num("mem_info_gtt_total"), "gtt_used_bytes": num("mem_info_gtt_used"),
    }


# ---- processes -------------------------------------------------------
def process_tree(pid: int) -> list[int]:
    out, stack = [], [pid]
    while stack:
        p = stack.pop()
        if not Path(f"/proc/{p}").exists():
            continue
        out.append(p)
        for task in Path(f"/proc/{p}/task").glob("*"):
            kids = _read(task / "children") or ""
            stack.extend(int(k) for k in kids.split())
    return out


def rss_bytes(pid: int) -> int:
    for line in (_read(f"/proc/{pid}/status") or "").splitlines():
        if line.startswith("VmRSS:"):
            return int(line.split()[1]) * 1024
    return 0


def gpu_bytes(pid: int) -> int:
    """GTT + VRAM held by the process's DRM clients, each client counted once."""
    seen: set[str] = set()
    total = 0
    fdinfo = Path(f"/proc/{pid}/fdinfo")
    try:
        entries = list(fdinfo.iterdir())
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


def footprint(pid: int | None) -> int | None:
    if not pid:
        return None
    tree = process_tree(pid)
    if not tree:
        return None
    return sum(rss_bytes(p) + gpu_bytes(p) for p in tree)


# ---- ports -----------------------------------------------------------
def port_free(port: int, host: str = "127.0.0.1") -> bool:
    """True when nothing listens on ``port`` (binding tests every address family
    that would collide with a 127.0.0.1 listener, including 0.0.0.0)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        # Like llama-server itself: TIME_WAIT leftovers do not block a bind,
        # only a live listener does.
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
        except OSError as e:
            if e.errno in (errno.EADDRINUSE, errno.EACCES):
                return False
            raise
    return True


def port_owner(port: int) -> str | None:
    """"python3 (pid 5816)" for whatever listens on ``port``, if ss can tell."""
    try:
        out = subprocess.run(["ss", "-ltnpH", f"sport = :{port}"], capture_output=True,
                             text=True, timeout=2).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    m = SS_USER_RE.search(out)
    return f"{m.group(1)} (pid {m.group(2)})" if m else ("another process" if out.strip() else None)
