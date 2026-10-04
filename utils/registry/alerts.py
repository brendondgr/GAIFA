"""Registry alerts (plan 3.5): kept current for missing, partial and checksum-mismatch models.

Alerts (brief `Alert`), with the same ids as the mock:
- `models-missing` (warn): "2 models have missing files" → `#/models?status=missing`
- `models-partial` (warn): "1 model is incomplete" → `#/models?status=partial`
- `sum-<id>` (error), one per mismatched model → `#/models/<id>`
- `registry-invalid` (error): registry.json or some of its entries can't be read

They are recomputed after every change, whenever the list is read, and once a
minute (files can disappear without the hub noticing). The same pass publishes a
`model` event for every model whose status changed.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from utils.registry.store import Registry

log = logging.getLogger("aihub.registry")

EVERY_S = 60.0
PREFIX = "sum-"
FIXED = ("models-missing", "models-partial", "registry-invalid")


def refresh(reg: Registry, views: list[dict[str, Any]] | None = None) -> None:
    alerts = reg.alerts
    if alerts is None:
        return
    if views is None:
        views = [reg.view(mid, e) for mid, e in sorted(reg.entries.items())]
    _publish_changes(reg, views)
    want: dict[str, tuple[str, str, dict[str, str]]] = {}
    missing = [v for v in views if v["status"] == "missing"]
    partial = [v for v in views if v["status"] == "partial"]
    if missing:
        n = len(missing)
        want["models-missing"] = ("warn", f"{n} model{'s have' if n > 1 else ' has'} missing files", {"label": "Review", "route": "#/models?status=missing"})
    if partial:
        n = len(partial)
        want["models-partial"] = ("warn", f"{n} model{'s are' if n > 1 else ' is'} incomplete", {"label": "Review", "route": "#/models?status=partial"})
    for v in views:
        if v["status"] == "checksum_mismatch":
            want[PREFIX + v["id"]] = ("error", f"Checksum mismatch: {v['name']}", {"label": "Open", "route": f"#/models/{v['id']}"})
    if reg.readonly:
        want["registry-invalid"] = ("error", f"Models registry: {reg.readonly}", {"label": "Open", "route": "#/models"})
    elif reg.errors:
        n = len(reg.errors)
        want["registry-invalid"] = ("error", f"registry.json: {n} entr{'ies' if n > 1 else 'y'} can't be read ({reg.errors[0]})", {"label": "Open", "route": "#/models"})
    for aid, (level, text, action) in want.items():
        alerts.set(aid, level, text, action=action)  # type: ignore[arg-type]
    for a in alerts.list():
        aid = a["id"]
        if (aid in FIXED or aid.startswith(PREFIX)) and aid not in want:
            alerts.clear(aid)


def _publish_changes(reg: Registry, views: list[dict[str, Any]]) -> None:
    """A `model` event for each model whose status changed since the last look: files that
    appear, vanish or change on disk send no event of their own."""
    seen = {v["id"]: v["status"] for v in views}
    last = reg.last_status
    if last is not None and reg.bus:
        for v in views:
            if last.get(v["id"], v["status"]) != v["status"] and v["status"] != "verifying":
                reg.bus.publish({"type": "model", "model": v})
    reg.last_status = seen


class Watcher:
    """Re-reads registry.json if it changed and refreshes the alerts every `every` seconds."""

    def __init__(self, reg: Registry, every: float = EVERY_S) -> None:
        self.reg = reg
        self.every = every
        self._task: asyncio.Task[None] | None = None
        reg.changed = lambda: refresh(reg)  # type: ignore[method-assign]

    def start(self) -> None:
        self.reg.refresh()
        refresh(self.reg)
        self._task = asyncio.create_task(self._run(), name="aihub-registry-watch")

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self.every)
            try:
                self.reg.refresh()
                refresh(self.reg)
            except Exception:  # noqa: BLE001: keep watching
                log.exception("registry alerts")

    async def close(self) -> None:
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
