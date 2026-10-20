"""The model runs in a child process, so unloading gives everything back.

A process that has imported torch keeps the ROCm runtime and the heap it read the weights into, about 3.5 GB
on gfx1151, even after the model is freed; handing that heap back with `malloc_trim` corrupted another
process's memory on 2026-10-20 (setup/embed.md, What to look for). So the server never imports torch: a
spawned worker loads the model, encodes on request, and unloading ends it. A GPU crash takes down the worker,
not the server: the next request starts a new one.
"""

from __future__ import annotations

import logging
import multiprocessing as mp
from collections.abc import Callable
from typing import Any

import numpy as np

from .encoder import Backend, footprint_bytes

log = logging.getLogger("embed")
ERRORS = {"FileNotFoundError": FileNotFoundError, "ValueError": ValueError}


class WorkerDied(RuntimeError):
    """The worker exited mid-call (a crash in the GPU runtime, or out of memory)."""


def serve(conn: Any, factory: Callable[[], Backend], parts: frozenset[str]) -> None:
    """The child: load, then answer ("encode", kind, items, batch) and ("load", parts) until ("exit",)."""
    backend = factory()
    msg: tuple = ("load", parts)
    while True:
        try:
            if msg[0] == "exit":
                return
            if msg[0] == "load":
                backend.load(msg[1])
                conn.send(("ok", {"device": backend.device, "dtype": backend.dtype}))
            else:
                conn.send(("ok", backend.encode(*msg[1:])))
        except Exception as e:                              # noqa: BLE001: every failure goes back to the server
            conn.send(("error", type(e).__name__, str(e)))
        try:
            msg = conn.recv()
        except EOFError:                                    # the server went away
            return


class WorkerBackend:
    """A Backend whose model lives in a spawned process. The first load starts it; a load with more parts
    reloads inside it (no new torch import); unload ends it."""

    def __init__(self, factory: Callable[[], Backend], timeout_s: float = 600):
        self.factory = factory
        self.timeout_s = timeout_s
        self.proc: Any = None
        self.conn: Any = None
        self.device = "cpu"
        self.dtype = "float32"

    def _call(self, msg: tuple | None) -> Any:
        if msg is not None:
            self.conn.send(msg)
        waited = 0
        while not self.conn.poll(1):
            waited += 1
            if not self.proc.is_alive():
                self._died()
            if waited > self.timeout_s:                     # hung (a GPU hang looks like this): end it
                log.error("the encoder worker didn't answer in %.0f s; killing it", self.timeout_s)
                self.proc.kill()
                self._died()
        try:
            reply = self.conn.recv()
        except EOFError:                                    # it exited: the pipe closes before is_alive() knows
            self._died()
        if reply[0] == "error":
            raise ERRORS.get(reply[1], RuntimeError)(reply[2])
        return reply[1]

    def load(self, parts: frozenset[str]) -> None:
        if self.proc is not None and self.proc.is_alive():
            info = self._call(("load", parts))
        else:
            ctx = mp.get_context("spawn")                   # never fork a process that may hold a GPU context
            self.conn, child = ctx.Pipe()
            self.proc = ctx.Process(target=serve, args=(child, self.factory, parts), name="embed-worker", daemon=True)
            self.proc.start()
            child.close()
            try:
                info = self._call(None)
            except Exception:
                self.unload()
                raise
        self.device, self.dtype = info["device"], info["dtype"]

    def encode(self, kind: str, items: list[Any], batch_size: int) -> np.ndarray:
        if self.proc is None:
            raise WorkerDied("the encoder isn't loaded")
        return self._call(("encode", kind, items, batch_size))

    def unload(self) -> None:
        if self.proc is None:
            return
        try:
            self.conn.send(("exit",))
        except (OSError, ValueError):
            pass
        self.proc.join(15)
        if self.proc.is_alive():
            log.warning("the encoder worker didn't exit; killing it")
            self.proc.kill()
            self.proc.join(5)
        self._reap()

    def _died(self) -> None:
        self.proc.join(5)
        code = self.proc.exitcode
        self._reap()
        raise WorkerDied(f"the encoder worker died (exit code {code}); the next call starts a new one")

    def _reap(self) -> None:
        if self.conn is not None:
            self.conn.close()
        self.proc = self.conn = None

    @property
    def alive(self) -> bool:
        return self.proc is not None

    def footprint_bytes(self) -> int:
        """The worker's memory plus this process's own (the server, without torch: tens of MB)."""
        return footprint_bytes() + (footprint_bytes(self.proc.pid) if self.proc is not None else 0)
