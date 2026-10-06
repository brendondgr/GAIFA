"""tasks.toml: the tasks packs implement and the shared input names (plan 11.5)."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT = Path(__file__).resolve().parents[1] / "tasks.toml"


@dataclass(frozen=True)
class Task:
    id: str
    name: str
    description: str
    required: tuple[str, ...]
    output: str | None
    tool: str | None


@dataclass
class Tasks:
    tasks: dict[str, Task] = field(default_factory=dict)
    inputs: dict[str, dict] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path = DEFAULT) -> Tasks:
        raw = tomllib.loads(path.read_text())
        tasks = {k: Task(k, v.get("name", k), v.get("description", ""), tuple(v.get("required", [])),
                         v.get("output"), v.get("tool")) for k, v in (raw.get("tasks") or {}).items()}
        return cls(tasks, raw.get("inputs") or {})

    def get(self, tid: str) -> Task | None:
        return self.tasks.get(tid)

    def derived(self) -> set[str]:
        return {k for k, v in self.inputs.items() if v.get("derived")}
