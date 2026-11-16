"""Changing the embed model (plan capability-enablement 7.3): the new model's index is built beside the one in use,
in the background, and search keeps using the old one until the new is ready. Then the choice is saved
(`<state>/model.json`) and the hub restarts the mod on the new model, whose index is complete. Switching back
finds the old index where it was: only what changed meanwhile is embedded again.

The build is a second `Library` on the new model's `Store` and `Encoder`: it lists the hub's outputs, copies the chat
summaries, texts (the agent's memory) and collections across, and drains under the same GPU lease and memory rules
as the library itself (background work, never evicting).
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import models
from .encoder import Encoder
from .library import Library
from .store import Store

log = logging.getLogger("embed")


class Switch:
    def __init__(self, lib: Library, make_encoder: Callable[[models.ModelInfo], Encoder],
                 on_done: Callable[[], Any] | None = None, pause_s: float = 5.0):
        self.lib = lib                                  # the library in use (search keeps using it)
        self.make_encoder = make_encoder
        self.on_done = on_done                          # restart on the new model (the hub); tests pass their own
        self.pause_s = pause_s
        self.job: dict[str, Any] | None = None
        self.task: asyncio.Task | None = None
        self.new: Library | None = None

    def start(self, info: models.ModelInfo) -> dict[str, Any]:
        if self.task is not None and not self.task.done():
            raise SwitchError("switch_busy", f"already switching to {self.job['model'] if self.job else '?'}",
                              "wait for it, or cancel it (DELETE /v1/model/switch)")
        if info.id == self.lib.enc.info.id:
            raise SwitchError("same_model", f"{info.name} is already the model in use", "")
        if not models.weights(info.folder):
            raise SwitchError("no_weights", f"no weights in {info.folder}",
                              f"download the model into {info.folder} (gaifa setup embed, the model question)")
        s = self.lib.s
        enc = self.make_encoder(info)
        store = Store(Path(s.databases) / models.db_name(info.id), info.dim)
        self.new = Library(store, enc, self.lib.hub, s, self.lib.gpu)
        self.job = {"model": info.id, "name": info.name, "state": "building", "started_ts": time.time(),
                    "done": 0, "pending": 0, "error": None}
        self.task = asyncio.create_task(self._build())
        return dict(self.job)

    def cancel(self) -> bool:
        if self.task is None or self.task.done():
            return False
        self.task.cancel()
        return True

    def status(self) -> dict[str, Any] | None:
        if self.job is None:
            return None
        if self.new is not None and self.job["state"] == "building":
            c = self.new.store.counts()
            self.job.update(done=c["done"], pending=c["pending"] + self.new.store.chat_counts()["pending"])
        return dict(self.job)

    async def _build(self) -> None:
        new = self.new
        assert new is not None and self.job is not None
        try:
            copied = new.store.copy_from(self.lib.store)
            log.info("switch to %s: copied %s", self.job["model"], copied)
            await new.reconcile()
            while True:
                await new.drain()
                if not new.store.pending(1) and not new.store.queued():
                    break
                if new.state == "error" and new.error:
                    self.job["error"] = new.error         # shown, and tried again after a pause
                await asyncio.sleep(self.pause_s)
            new.store.copy_from(self.lib.store)            # what came in during the build
            await new.index_chats()
            models.choose(Path(self.lib.s.state_dir), self.job["model"])
            c = new.store.counts()
            self.job.update(state="done", finished_ts=time.time(), error=None, done=c["done"], pending=c["pending"])
            log.info("switch to %s: index ready; restarting on it", self.job["model"])
        except asyncio.CancelledError:
            self.job.update(state="cancelled")
            raise
        except Exception as e:                           # noqa: BLE001: reported, the old model stays in use
            log.exception("switch failed")
            self.job.update(state="failed", error=f"{type(e).__name__}: {e}"[:500])
            return
        finally:
            await asyncio.to_thread(new.enc.unload)
            new.store.close()
        if self.on_done is not None:
            r = self.on_done()
            if asyncio.iscoroutine(r):
                await r


class SwitchError(Exception):
    def __init__(self, code: str, detail: str, fix: str):
        super().__init__(detail)
        self.code, self.detail, self.fix = code, detail, fix
