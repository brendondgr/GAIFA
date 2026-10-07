"""Where lcpp keeps things.

Everything hangs off one repo root so tests can point a whole instance of lcpp
at a temporary directory. Runtime state lives in ``LCPP_STATE_DIR`` (under AIHub:
``data/state/lcpp``, which survives reboots: the reconcile forgets records from before
the last boot), else ``$XDG_RUNTIME_DIR/lcpp`` (tmpfs).
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
    models: Path | None = None  # LCPP_MODELS_DIR; None = <root>/models

    @classmethod
    def default(cls) -> "Paths":
        root = Path(os.environ.get("LCPP_HOME") or REPO_ROOT)
        models = os.environ.get("LCPP_MODELS_DIR")
        return cls(root=root, state=_default_state_dir(),
                   models=Path(os.path.expanduser(models)) if models else None)

    @property
    def models_dir(self) -> Path:
        """Where GGUFs live: catalog paths are relative to it, and downloads land in it."""
        return self.models or self.root / "models"

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

    def model(self, value: str | os.PathLike[str]) -> Path:
        """A catalog path: ``~``/``$VARS`` expanded; relative paths are relative to the models folder."""
        raw = Path(os.path.expandvars(os.path.expanduser(str(value))))
        if raw.is_absolute():
            return raw
        if raw.parts[:1] == ("models",):  # the old repo-relative form: "models/X/f.gguf"
            raw = Path(*raw.parts[1:])
        return self.models_dir / raw

    def display_model(self, path: str | os.PathLike[str]) -> str:
        """A model file the way the catalog stores it: models-relative, else ``~/``-relative."""
        p = self.model(path)
        try:
            return str(p.relative_to(self.models_dir))
        except ValueError:
            pass
        try:
            return "~/" + str(p.relative_to(Path.home()))
        except ValueError:
            return str(p)  # absolute: model() reads it back unchanged

    def scan_dir(self, value: str) -> Path:
        """A ``scan_dirs`` entry; "models" (the default) means the models folder, wherever it is."""
        return self.models_dir if value.strip().rstrip("/") == "models" else self.resolve(value)

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
