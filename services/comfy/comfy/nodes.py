"""The node catalog: ComfyUI's /object_info, cached on disk (data/object_info.json) so packs can
be converted and checked while ComfyUI is down. Refreshed at every load."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

WIDGET_TYPES = {"INT", "FLOAT", "STRING", "BOOLEAN", "COMBO"}


@dataclass(frozen=True)
class InputSpec:
    name: str
    type: str                 # INT, FLOAT, STRING, BOOLEAN, COMBO, or a link type (MODEL, IMAGE, …)
    options: dict             # default, min, max, step, multiline, …
    choices: list | None      # COMBO values (for loaders: the files they can see)
    required: bool

    @property
    def widget(self) -> bool:
        """Shown as a widget in the editor (and so has a value in widgets_values)."""
        return self.type in WIDGET_TYPES and not self.options.get("forceInput")


def _spec(name: str, raw: list, required: bool) -> InputSpec:
    t = raw[0] if raw else "*"
    opts = raw[1] if len(raw) > 1 and isinstance(raw[1], dict) else {}
    if isinstance(t, list):                    # old style: the list itself is the COMBO
        return InputSpec(name, "COMBO", opts, list(t), required)
    if t == "COMBO":                           # new style: options["options"]
        return InputSpec(name, "COMBO", opts, list(opts.get("options") or []), required)
    return InputSpec(name, str(t), opts, None, required)


class NodeCatalog:
    def __init__(self, info: dict[str, Any] | None = None, path: Path | None = None):
        self.info: dict[str, Any] = info or {}
        self.path = path

    @classmethod
    def load(cls, path: Path) -> NodeCatalog:
        try:
            return cls(json.loads(path.read_text()), path)
        except (OSError, ValueError):
            return cls({}, path)

    def save(self, info: dict) -> None:
        self.info = info
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".part")
            tmp.write_text(json.dumps(info))
            os.replace(tmp, self.path)

    def __bool__(self) -> bool:
        return bool(self.info)

    def has(self, cls: str) -> bool:
        return cls in self.info

    def node(self, cls: str) -> dict | None:
        return self.info.get(cls)

    def inputs(self, cls: str) -> list[InputSpec]:
        """Inputs in the editor's order (input_order when given), required first."""
        n = self.info.get(cls)
        if not n:
            return []
        out = []
        order = n.get("input_order") or {}
        for section in ("required", "optional"):
            group = (n.get("input") or {}).get(section) or {}
            names = order.get(section) or list(group)
            out += [_spec(k, group[k], section == "required") for k in names if k in group]
        return out

    def input(self, cls: str, name: str) -> InputSpec | None:
        return next((i for i in self.inputs(cls) if i.name == name), None)

    def outputs(self, cls: str) -> list[str]:
        n = self.info.get(cls) or {}
        return list(n.get("output") or [])

    def is_output(self, cls: str) -> bool:
        return bool((self.info.get(cls) or {}).get("output_node"))

    def category(self, cls: str) -> str:
        return (self.info.get(cls) or {}).get("category") or ""

    def python_module(self, cls: str) -> str:
        return (self.info.get(cls) or {}).get("python_module") or ""
