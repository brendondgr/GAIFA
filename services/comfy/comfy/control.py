"""Starting and stopping ComfyUI (bin/comfyui), its liveness and queue, and idle unload.

`loaded` (for GAIFA) means the ComfyUI process is up. Unload frees its models and stops the
process (`comfyui quit`), so all of its memory comes back; the toolbox container keeps running
and starts ComfyUI again in ~15 s. Shutdown stops the container too."""

from __future__ import annotations

import asyncio
import logging
import time

from fastapi import APIRouter, HTTPException, Request

from .client import ComfyClient
from .nodes import NodeCatalog

log = logging.getLogger("comfy")
router = APIRouter()
POLL_S = 2.0          # tests patch this down


class Controller:
    def __init__(self, client: ComfyClient, catalog: NodeCatalog, control: str, load_timeout_s: float = 600,
                 idle_unload_s: float = 0):
        self.client, self.catalog, self.control = client, catalog, control
        self.load_timeout_s, self.idle_unload_s = load_timeout_s, idle_unload_s
        self.up = False
        self.running: list = []          # ComfyUI's queue_running entries
        self.pending: list = []
        self.last_activity = time.monotonic()
        self.state = "idle"              # idle | loading | unloading
        self._lock = asyncio.Lock()
        self._catalog_fresh = False
        self._stop = asyncio.Event()

    def stop(self) -> None:
        self._stop.set()

    @property
    def busy(self) -> bool:
        return bool(self.running or self.pending)

    def touch(self) -> None:
        self.last_activity = time.monotonic()

    async def _script(self, *args: str, timeout: float) -> tuple[int, str]:
        proc = await asyncio.create_subprocess_exec(self.control, *args, stdout=asyncio.subprocess.PIPE,
                                                    stderr=asyncio.subprocess.STDOUT)
        lines: list[str] = []

        async def pump():
            async for raw in proc.stdout:
                line = raw.decode("utf-8", "replace").rstrip()
                lines.append(line)
                log.info("%s", line)
        try:
            await asyncio.wait_for(asyncio.gather(pump(), proc.wait()), timeout)
        except TimeoutError:
            proc.kill()
            return -1, "\n".join(lines[-20:] + [f"timed out after {timeout:.0f}s"])
        return proc.returncode, "\n".join(lines[-20:])

    async def refresh_catalog(self) -> None:
        try:
            self.catalog.save(await self.client.object_info())
            self._catalog_fresh = True
            log.info("node catalog: %d node types", len(self.catalog.info))
        except Exception as e:  # noqa: BLE001 - keep the cached one
            log.warning("node catalog not refreshed: %s", e)

    async def load(self) -> None:
        async with self._lock:
            if await self.client.up():
                self.up = True
            else:
                self.state = "loading"
                try:
                    code, out = await self._script("start", timeout=self.load_timeout_s)
                finally:
                    self.state = "idle"
                self.up = await self.client.up()
                if not self.up:
                    raise HTTPException(503, f"ComfyUI didn't start (exit {code}): {out[-1500:]}")
            self.touch()
            await self.refresh_catalog()

    async def unload(self) -> None:
        async with self._lock:
            if not await self.client.up():
                self.up = False
                return
            self.state = "unloading"
            try:
                try:
                    await self.client.free()
                except Exception as e:  # noqa: BLE001 - stopping frees it anyway
                    log.warning("/free failed: %s", e)
                code, out = await self._script("quit", timeout=60)
            finally:
                self.state = "idle"
            self.up = await self.client.up()
            if self.up:
                raise HTTPException(500, f"ComfyUI is still running after quit (exit {code}): {out[-800:]}")
            self.running, self.pending = [], []

    async def shutdown(self) -> None:
        async with self._lock:
            await self._script("stop", timeout=120)
            self.up = False
            self.running, self.pending = [], []

    async def poll_once(self) -> None:
        up = await self.client.up()
        if up and not self.up:
            self.touch()               # adopted (started outside GAIFA, or the adapter restarted)
        self.up = up
        if not up:
            self.running, self.pending = [], []
            return
        if not self._catalog_fresh:
            await self.refresh_catalog()
        try:
            q = await self.client.queue()
            self.running, self.pending = q.get("queue_running") or [], q.get("queue_pending") or []
        except Exception:  # noqa: BLE001
            return
        if self.busy:
            self.touch()
        elif (self.idle_unload_s > 0 and self.state == "idle"
              and time.monotonic() - self.last_activity > self.idle_unload_s):
            log.info("idle for %.0fs: unloading", time.monotonic() - self.last_activity)
            try:
                await self.unload()
            except HTTPException as e:
                log.warning("idle unload failed: %s", e.detail)

    async def run(self) -> None:
        while not self._stop.is_set():
            try:
                await self.poll_once()
            except Exception:  # noqa: BLE001 - never let the poller die
                log.exception("poll failed")
            try:
                await asyncio.wait_for(self._stop.wait(), POLL_S)
            except TimeoutError:
                pass


@router.post("/v1/load", summary="Start ComfyUI (in its toolbox) and wait until it answers")
async def load(request: Request) -> dict:
    await request.app.state.control.load()
    return {"loaded": True}


@router.post("/v1/unload", summary="Free ComfyUI's models and stop its process (the toolbox stays up)")
async def unload(request: Request) -> dict:
    await request.app.state.control.unload()
    return {"loaded": False}


@router.post("/v1/shutdown", summary="Stop ComfyUI and its toolbox container")
async def shutdown(request: Request) -> dict:
    await request.app.state.control.shutdown()
    return {"loaded": False}
