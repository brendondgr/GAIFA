"""Where lcpp keeps things.

Everything hangs off one repo root so tests can point a whole instance of lcpp
at a temporary directory. Runtime state lives in ``$XDG_RUNTIME_DIR`` (tmpfs):
it is gone after a reboot, which is exactly the "nothing runs at boot" rule —
there is no stale instance record to reconcile against after a power cycle.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _default_state_dir() -> Path:
    override = os.environ.get("LCPP_STATE_DIR")
    if override:
        return Path(override)
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/tmp/lcpp-{os.getuid()}"
    return Path(runtime) / "lcpp"


@dataclass(frozen=True)
class Paths:
    root: Path
    state: Path

    @classmethod
    def default(cls) -> "Paths":
        root = Path(os.environ.get("LCPP_HOME") or REPO_ROOT)
        return cls(root=root, state=_default_state_dir())

    @property
    def data(self) -> Path:
        return self.root / "data"

    @property
    def settings_file(self) -> Path:
        return self.data / "lcpp.json"

    @property
    def models_file(self) -> Path:
        return self.data / "models.json"

    @property
    def recent_file(self) -> Path:
        return self.data / "recent.local.json"

    @property
    def generated(self) -> Path:
        return self.data / "generated"

    @property
    def web(self) -> Path:
        return self.root / "web"

    @property
    def instances(self) -> Path:
        return self.state / "instances"

    def resolve(self, value: str | os.PathLike[str]) -> Path:
        """Expand ``~``/``$VARS``; relative paths are relative to the repo root."""
        raw = Path(os.path.expandvars(os.path.expanduser(str(value))))
        return raw if raw.is_absolute() else self.root / raw

    def display(self, path: str | os.PathLike[str]) -> str:
        """The short form shown to people: repo-relative, else ``~/``-relative."""
        p = self.resolve(path)
        try:
            return str(p.relative_to(self.root))
        except ValueError:
            pass
        home = Path.home()
        try:
            return "~/" + str(p.relative_to(home))
        except ValueError:
            return str(p)


def write_atomic(path: Path, text: str) -> None:
    """Write via a temp file + rename so a crash never leaves half a JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
