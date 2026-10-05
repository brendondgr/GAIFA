"""The outputs watcher (plan 4.2): `watchfiles` on `outputs/`, so new outputs appear live.

- Each change marks its folder (`<service>/<date>` or `<service>`) dirty, batched by
  `watchfiles` for up to 1 s. A dirty folder is rescanned; an output whose sizes changed
  since the last look waits another `stable_s` and is indexed once they hold still.
- Deletions apply at once. Dotfiles (previews, `.trash`) and `*.part` never count.
- **Startup:** a background `reconcile()` (no event per output), then the trash is purged,
  and again every 6 hours.
- If watching fails (e.g. `outputs/` was removed), an `outputs-watch` alert is raised,
  and the watcher retries every 5 s and rescans everything once it is back.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from pathlib import Path
from typing import Any

from watchfiles import Change, awatch

from utils.outputs import trash
from utils.outputs.announce import Announcer
from utils.outputs.entries import scope_for
from utils.outputs.index import Outputs

log = logging.getLogger("aihub.outputs")

STABLE_S = 1.0
DEBOUNCE_MS = 1000
RETRY_S = 5.0
PURGE_EVERY_S = 6 * 3600
ALERT = "outputs-watch"


class Watcher:
    def __init__(self, outputs: Outputs, alerts: Any = None, name_of: Any = None, *, stable_s: float = STABLE_S,
                 debounce_ms: int = DEBOUNCE_MS, retry_s: float = RETRY_S, reconcile: bool = True) -> None:
        self.outputs = outputs
        self.dir: Path = outputs.dir
        self.alerts = alerts
        self.stable_s, self.debounce_ms, self.retry_s = stable_s, debounce_ms, retry_s
        self.do_reconcile = reconcile
        self.pending: dict[str, tuple[str, float]] = {}  # rel → (sig, when first seen)
        self._dirty: dict[str, float] = {}  # scope → when to look at it
        self._wake = asyncio.Event()
        self._stop = asyncio.Event()
        self._tasks: list[asyncio.Task[None]] = []
        self.ready = asyncio.Event()  # set once the startup reconcile is done
        if outputs.activity is not None:
            outputs.announcer = Announcer(outputs.activity, name_of or (lambda s: s))

    def start(self) -> None:
        self._tasks = [
            asyncio.create_task(self._watch(), name="aihub-outputs-watch"),
            asyncio.create_task(self._process(), name="aihub-outputs-index"),
            asyncio.create_task(self._housekeeping(), name="aihub-outputs-housekeeping"),
        ]

    async def close(self) -> None:
        self._stop.set()
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        if self.outputs.announcer:
            await self.outputs.announcer.close()

    def mark(self, scope: str, at: float | None = None) -> None:
        self._dirty.setdefault(scope, time.monotonic() if at is None else at)
        self._wake.set()

    def _filter(self, _change: Change, path: str) -> bool:
        return scope_for(self.dir, Path(path)) is not None

    async def _watch(self) -> None:
        failed = False
        while not self._stop.is_set():
            try:
                self.dir.mkdir(parents=True, exist_ok=True)
                if failed:
                    self.mark("")  # events were missed while it was down
                watching = awatch(self.dir, watch_filter=self._filter, debounce=self.debounce_ms, step=50,
                                  stop_event=self._stop, recursive=True, yield_on_timeout=True, rust_timeout=1000)
                async for changes in watching:
                    if failed:
                        failed = False
                        if self.alerts:
                            self.alerts.clear(ALERT)
                    for _, p in changes:
                        scope = scope_for(self.dir, Path(p))
                        if scope is not None:
                            self.mark(scope)
                    if not self.dir.is_dir():
                        raise FileNotFoundError(f"{self.dir} is gone")
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001: report, then keep trying
                if not failed:
                    log.warning("outputs watcher: %s", e)
                    if self.alerts:
                        self.alerts.set(ALERT, "error", f"Outputs watcher stopped: {e}. New outputs won't appear until it recovers.",
                                        action={"label": "Logs", "route": "#/settings/about"})
                failed = True
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._stop.wait(), self.retry_s)

    async def _process(self) -> None:
        while True:
            now = time.monotonic()
            due = [s for s, at in self._dirty.items() if at <= now]
            if not due:
                wait = min(self._dirty.values()) - now if self._dirty else None
                self._wake.clear()
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._wake.wait(), wait)
                continue
            if "" in due:  # everything: the narrower scopes are covered
                due = [""]
                self._dirty.clear()
            for s in due:
                self._dirty.pop(s, None)
                try:
                    settling = await self.outputs.sync(s, pending=self.pending, stable_s=self.stable_s)
                except Exception:  # noqa: BLE001: one bad folder must not stop the rest
                    log.exception("outputs: indexing %s", s or "outputs/")
                    settling = False
                if settling:
                    self.mark(s, time.monotonic() + self.stable_s)

    async def _housekeeping(self) -> None:
        if self.do_reconcile:
            try:
                await self.outputs.reconcile()
            except Exception:  # noqa: BLE001
                log.exception("outputs: startup rescan")
        self.ready.set()
        while True:
            try:
                await asyncio.to_thread(trash.purge, self.dir)
            except Exception:  # noqa: BLE001
                log.exception("outputs: purging the trash")
            await asyncio.sleep(PURGE_EVERY_S)
