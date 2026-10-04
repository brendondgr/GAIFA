"""Project paths and atomic file writes.

The project root is the folder holding `app.py` (this file's parent's parent),
or `AIHUB_ROOT` when set. Everything the hub writes lives under it.
Nothing here touches the filesystem until `Paths.ensure()` is called.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

DEFAULT_ROOT = Path(__file__).resolve().parent.parent


def project_root() -> Path:
    """`AIHUB_ROOT` if set, else the folder holding `app.py`."""
    env = os.environ.get("AIHUB_ROOT")
    return Path(env).expanduser().resolve() if env else DEFAULT_ROOT


@dataclass(frozen=True)
class Paths:
    root: Path
    models: Path
    databases: Path
    outputs: Path

    @classmethod
    def build(
        cls,
        root: Path | None = None,
        models: str = "data/models",
        databases: str = "data/databases",
        outputs: str = "outputs",
    ) -> Paths:
        """Resolve the configurable dirs against `root` (they are relative to config.toml)."""
        root = (root or project_root()).resolve()
        return cls(
            root=root,
            models=_inside(root, models, "paths.models"),
            databases=_inside(root, databases, "paths.databases"),
            outputs=_inside(root, outputs, "paths.outputs"),
        )

    @property
    def config_file(self) -> Path:
        return self.root / "config.toml"

    @property
    def web(self) -> Path:
        return self.root / "web"

    @property
    def services(self) -> Path:
        return self.root / "services"

    @property
    def hub_db(self) -> Path:
        return self.databases / "hub.db"

    @property
    def registry(self) -> Path:
        return self.models / "registry.json"

    def ensure(self) -> None:
        """Create the derived dirs. Called on startup, never at import."""
        for d in (self.models, self.databases, self.outputs):
            d.mkdir(parents=True, exist_ok=True)

    def rel(self, p: Path) -> str:
        """`p` relative to the root, for display ("outputs/tts")."""
        try:
            return str(p.resolve().relative_to(self.root))
        except ValueError:
            return str(p)


def _inside(root: Path, value: str, key: str) -> Path:
    p = (root / value).resolve()
    if not p.is_relative_to(root):
        raise ValueError(f"{key}: {value!r} is outside the project root {root}")
    return p


def write_atomic(path: Path, data: str | bytes) -> None:
    """Write to a temp file in the same dir, fsync it, then rename over `path`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = data.encode() if isinstance(data, str) else data
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(raw)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, path.stat().st_mode & 0o777 if path.exists() else 0o644)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    dfd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(dfd)
    finally:
        os.close(dfd)
