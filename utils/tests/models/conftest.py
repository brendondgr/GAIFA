"""Fixtures for the models registry tests: a temp `data/models/` and a Registry on it."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pytest

from utils.events import EventBus
from utils.paths import Paths
from utils.registry import Registry
from utils.registry.model import now_iso


class Models:
    """Write fake model files and registry entries under `<root>/data/models`."""

    def __init__(self, root: Path) -> None:
        self.paths = Paths.build(root)
        self.paths.ensure()
        self.dir = self.paths.models

    def put(self, rel: str, data: bytes | int = 16, mtime: float | None = None) -> Path:
        """A file of `data` bytes (or `data` zero-free bytes when an int)."""
        p = self.dir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data if isinstance(data, bytes) else bytes((i % 251) + 1 for i in range(data)))
        if mtime is not None:
            os.utime(p, (mtime, mtime))
        return p

    def file(self, rel: str, role: str = "weights", verified: bool = False, **extra: Any) -> dict[str, Any]:
        """A registry file record for an existing file, optionally with its checksum recorded."""
        p = self.dir / rel
        f: dict[str, Any] = {"path": rel, "role": role, "size_bytes": p.stat().st_size if p.exists() else 1000, "sha256": None, "verified_at": None}
        if verified:
            f["sha256"] = hashlib.sha256(p.read_bytes()).hexdigest()
            f["verified_at"] = now_iso()
        f.update(extra)
        return f

    def write(self, models: dict[str, dict[str, Any]], version: int = 1) -> None:
        full = {}
        for mid, m in models.items():
            full[mid] = {"name": mid, "kind": "other", "format": "", "path": m.get("path") or (m["files"][0]["path"] if m.get("files") else "x"), "services": [], "source": None, "added": "2026-10-04T12:00:00-04:00", "tags": [], "notes": "", **m}
        self.paths.registry.write_text(json.dumps({"version": version, "models": full}, indent=2))

    def read(self) -> dict[str, Any]:
        return json.loads(self.paths.registry.read_text())


@pytest.fixture
def models(root) -> Models:
    return Models(root)


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


@pytest.fixture
def reg(models, bus) -> Registry:
    r = Registry(models.paths, bus)
    r.load()
    return r
