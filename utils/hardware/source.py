"""Where hardware detection reads the machine (plan 35.1): live, recorded, or from a snapshot.

Every reader in `utils/hardware/` goes through a `Source`, so a machine can be recorded once
(`Recorder`, `gaifa hardware --snapshot`) and replayed anywhere (`Snapshot`): the test fixtures
and the field reports (plan 40.2) are such recordings. Standard library only: `gaifa setup` runs
this from a bare clone.
"""

from __future__ import annotations

import glob as globmod
import os
import platform as platmod
import re
import shutil
import subprocess
from functools import cache
from pathlib import Path
from typing import Any

CMD_TIMEOUT_S = 10
PCI_IDS = ("/usr/share/hwdata/pci.ids", "/usr/share/misc/pci.ids", "/usr/share/pci.ids")


@cache
def _pci_table(path: str) -> dict[str, str]:
    """`vendor:device` → the device's name, from pci.ids (read once, only the display vendors)."""
    out: dict[str, str] = {}
    vendor = ""
    try:
        text = Path(path).read_text(errors="replace")
    except OSError:
        return out
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        if not line.startswith("\t"):
            vendor = line[:4] if line[:4] in ("1002", "10de", "8086") else ""
        elif vendor and not line.startswith("\t\t"):
            dev, _, name = line.strip().partition(" ")
            out[f"{vendor}:{dev}"] = name.strip()
    return out


class Source:
    """The live machine. Every method answers None (or empty) when the thing isn't there."""

    def platform(self) -> dict[str, Any]:
        return {"system": platmod.system().lower(), "machine": platmod.machine().lower(),
                "release": platmod.release(), "cpus": os.cpu_count() or 0}

    def read(self, path: str, limit: int = 65536) -> str | None:
        try:
            with open(path, errors="replace") as f:
                return f.read(limit)
        except OSError:
            return None

    def ls(self, path: str) -> list[str] | None:
        try:
            return sorted(os.listdir(path))
        except OSError:
            return None

    def link(self, path: str) -> str | None:
        try:
            return os.readlink(path)
        except OSError:
            return None

    def glob(self, pattern: str) -> list[str]:
        return sorted(globmod.glob(pattern))

    def which(self, cmd: str) -> str | None:
        return shutil.which(cmd)

    def run(self, argv: list[str]) -> str | None:
        """stdout of a command that exited 0, else None (missing, failed or too slow)."""
        try:
            p = subprocess.run(argv, capture_output=True, text=True, timeout=CMD_TIMEOUT_S)
        except (OSError, subprocess.SubprocessError):
            return None
        return p.stdout if p.returncode == 0 else None

    def pci_name(self, vendor: str, device: str) -> str | None:
        for path in PCI_IDS:
            table = _pci_table(path)
            if table:
                return table.get(f"{vendor}:{device}")
        return None


class Recorder(Source):
    """A live source that remembers everything it was asked, as a snapshot."""

    def __init__(self, inner: Source | None = None) -> None:
        self.inner = inner or Source()
        self.data: dict[str, Any] = {"platform": None, "files": {}, "dirs": {}, "links": {}, "globs": {}, "which": {}, "cmds": {}, "pci": {}}

    def platform(self) -> dict[str, Any]:
        self.data["platform"] = v = self.inner.platform()
        return v

    def read(self, path: str, limit: int = 65536) -> str | None:
        self.data["files"][path] = v = self.inner.read(path, limit)
        return v

    def ls(self, path: str) -> list[str] | None:
        self.data["dirs"][path] = v = self.inner.ls(path)
        return v

    def link(self, path: str) -> str | None:
        self.data["links"][path] = v = self.inner.link(path)
        return v

    def glob(self, pattern: str) -> list[str]:
        self.data["globs"][pattern] = v = self.inner.glob(pattern)
        return v

    def which(self, cmd: str) -> str | None:
        self.data["which"][cmd] = v = self.inner.which(cmd)
        return v

    def run(self, argv: list[str]) -> str | None:
        self.data["cmds"][" ".join(argv)] = v = self.inner.run(argv)
        return v

    def pci_name(self, vendor: str, device: str) -> str | None:
        self.data["pci"][f"{vendor}:{device}"] = v = self.inner.pci_name(vendor, device)
        return v


class Snapshot(Source):
    """A recorded machine. Anything the recording didn't ask about reads as missing."""

    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data

    def platform(self) -> dict[str, Any]:
        return dict(self.data["platform"])

    def read(self, path: str, limit: int = 65536) -> str | None:
        v = self.data.get("files", {}).get(path)
        return None if v is None else v[:limit]

    def ls(self, path: str) -> list[str] | None:
        return self.data.get("dirs", {}).get(path)

    def link(self, path: str) -> str | None:
        return self.data.get("links", {}).get(path)

    def glob(self, pattern: str) -> list[str]:
        return list(self.data.get("globs", {}).get(pattern) or [])

    def which(self, cmd: str) -> str | None:
        return self.data.get("which", {}).get(cmd)

    def run(self, argv: list[str]) -> str | None:
        return self.data.get("cmds", {}).get(" ".join(argv))

    def pci_name(self, vendor: str, device: str) -> str | None:
        return self.data.get("pci", {}).get(f"{vendor}:{device}")


def first_match(pattern: str, text: str | None, flags: int = re.M) -> str | None:
    m = re.search(pattern, text or "", flags)
    return m.group(1).strip() if m else None
