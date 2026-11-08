"""What each page remembers, on the hub (plan settings-that-stick 4.1): a mod page's choices (a voice, a preset, a
filter) and the hub's own view state (the open chat panes, folded Settings groups, a table's sort), so nothing a
person chooses lives only in one browser.

One small JSON file per scope, `data/state/ui/<scope>.json` (`gaifa backup` copies `data/state/*/*.json`); a scope
is a mod id or `hub`. Values are free-form JSON the hub doesn't interpret; each is at most 16 KB and a file at most
256 KB. A change names the keys it sets and deletes, so two pages never overwrite each other's keys.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from utils.paths import write_atomic

KEY_MAX = 128
VALUE_MAX = 16 * 1024
FILE_MAX = 256 * 1024


class StoreError(ValueError):
    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status


class UiStore:
    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self._lock = threading.Lock()

    def _file(self, scope: str) -> Path:
        return self.folder / f"{scope}.json"

    def get(self, scope: str) -> dict[str, Any]:
        p = self._file(scope)
        try:
            data = json.loads(p.read_text())
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def change(self, scope: str, set_: dict[str, Any] | None = None, delete: list[str] | None = None) -> tuple[dict[str, Any], list[str]]:
        """Set and delete keys; returns the values and the keys that changed. Raises StoreError (413/422)."""
        set_, delete = set_ or {}, delete or []
        for k, v in set_.items():
            if not k or len(k) > KEY_MAX:
                raise StoreError(422, f"key {k[:40]!r}: 1-{KEY_MAX} characters")
            if len(json.dumps(v)) > VALUE_MAX:
                raise StoreError(413, f"{k}: a value is at most {VALUE_MAX // 1024} KB")
        with self._lock:
            cur = self.get(scope)
            new = {**{k: v for k, v in cur.items() if k not in delete}, **set_}
            changed = sorted(k for k in {*cur, *new} if cur.get(k, ...) != new.get(k, ...))
            if not changed:
                return cur, []
            text = json.dumps(new, ensure_ascii=False, sort_keys=True)
            if len(text.encode()) > FILE_MAX:
                raise StoreError(413, f"{scope}: the store is at most {FILE_MAX // 1024} KB")
            write_atomic(self._file(scope), text + "\n")
            return new, changed
