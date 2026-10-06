"""Instance records and their on-disk state (``$XDG_RUNTIME_DIR/lcpp``).

One JSON file per instance, rewritten on every state transition, so a daemon
restart can pick up exactly where the last one left off. The directory is
tmpfs: after a reboot there are no records and no units, i.e. nothing runs.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from lcpp.paths import write_atomic
from lcpp.settings import HOST

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,47}$")
STATES = ("starting", "ready", "stopping", "failed")


class LcppError(Exception):
    """An error with an API code (see docs/api.md) and an HTTP status."""

    def __init__(self, code: str, detail: str, status: int = 400, field: str | None = None,
                 data: dict | None = None):
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.status = status
        self.field = field
        self.data = data  # extra context, e.g. AIHub's make-room plan for needs_room


def relay_off() -> dict[str, Any]:
    return {"enabled": False, "state": "off", "key": None, "alias": None, "health": None, "error": None}


@dataclass
class Instance:
    name: str
    kind: str  # "single" | "router"
    port: int
    spec: dict[str, Any]
    model_id: str | None
    model_ids: list[str]
    models_max: int
    params: dict[str, Any]
    argv: list[str]
    capabilities: dict[str, bool]
    relay: dict[str, Any] = field(default_factory=relay_off)
    state: str = "starting"
    pid: int | None = None
    invocation: str | None = None
    started_ts: float = 0.0
    ready_ts: float | None = None
    last_error: str | None = None
    last_log_lines: list[str] = field(default_factory=list)

    @property
    def base(self) -> str:
        return f"http://{HOST}:{self.port}"

    @property
    def url(self) -> str:
        return f"{self.base}/v1"

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> "Instance":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in raw.items() if k in known})


class InstanceStore:
    def __init__(self, directory: Path):
        self.dir = directory

    def _path(self, name: str) -> Path:
        return self.dir / f"{name}.json"

    def save(self, inst: Instance) -> None:
        write_atomic(self._path(inst.name), json.dumps(inst.to_json(), indent=2))

    def delete(self, name: str) -> None:
        self._path(name).unlink(missing_ok=True)

    def load_all(self) -> list[Instance]:
        if not self.dir.is_dir():
            return []
        out = []
        for p in sorted(self.dir.glob("*.json")):
            try:
                out.append(Instance.from_json(json.loads(p.read_text())))
            except (json.JSONDecodeError, TypeError):
                p.unlink(missing_ok=True)
        return out
