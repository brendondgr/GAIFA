"""Process facts read from /proc: who listens on a port (more arrives with Phase 5's memory sampling)."""

from __future__ import annotations

import os
import socket
from pathlib import Path

PROC = Path("/proc")
LISTEN = "0A"


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
