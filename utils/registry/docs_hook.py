"""The setup docs follow the registry (plan 23.3): every change rewrites the affected model docs
and the index, debounced and off the event loop. `[docs] regenerate = false` turns it off."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from pathlib import Path

from utils import setupdocs
from utils.registry.store import Registry

log = logging.getLogger("aihub.docs")
DEBOUNCE_S = 2.0


class DocsHook:
    def __init__(self, reg: Registry, root: Path, enabled: Callable[[], bool], debounce_s: float = DEBOUNCE_S) -> None:
        self.root, self.enabled, self.debounce_s = root, enabled, debounce_s
        self._ids: set[str] | None = set()      # None: every model
        self._task: asyncio.Task[None] | None = None
        self.runs = 0                            # syncs done (tests)
        reg.subscribe(self.changed)

    def start(self) -> None:
        """One full pass at boot: catches registry edits made while the hub was down."""
        self.changed(None)

    def changed(self, model_id: str | None) -> None:
        if not self.enabled():
            return
        if model_id is None or self._ids is None:
            self._ids = None
        else:
            self._ids.add(model_id)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return                               # no loop (a script): `aihub docs` covers it
        if self._task is None or self._task.done():
            self._task = loop.create_task(self._run(), name="aihub-setup-docs")

    async def _run(self) -> None:
        await asyncio.sleep(self.debounce_s)
        ids, self._ids = self._ids, set()
        try:
            report = await asyncio.to_thread(setupdocs.sync, self.root, None if ids is None else sorted(ids))
            self.runs += 1
            for rel in report.written + report.removed:
                log.info("setup docs: %s", rel)
        except Exception:  # noqa: BLE001: docs never break the registry
            log.exception("setup docs")
        if self._ids:                            # changes that came in while writing
            self._task = asyncio.get_running_loop().create_task(self._run(), name="aihub-setup-docs")

    async def close(self) -> None:
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
