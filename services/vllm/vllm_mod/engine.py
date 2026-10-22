"""The engine: at most one vLLM container, from load to unload (plan 18.2).

unloaded → starting → ready → stopping → unloaded, and starting/ready → failed when the container exits
on its own or doesn't become healthy in time. A load asks AIHub for the profile's memory first, then
starts the container and waits for vLLM's /health; stages come from its log. On adapter start, a
container left running (an adapter crash) is adopted; stopping the adapter stops the engine.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections import deque
from collections.abc import Awaitable, Callable
from contextlib import suppress
from typing import Any

import httpx

from .containers import ContainerError, FakeContainers, Podman
from .hubclient import Hub, NeedsRoom
from .profiles import Profile, engine_command, load_profiles
from .settings import Settings, gtt_total_bytes

log = logging.getLogger("vllm")
Hook = Callable[[Profile], Awaitable[None]]

# vLLM's log milestones → the stage shown while starting (checked in order; the last match wins).
STAGES = [
    (re.compile(r"Initializing a V1 LLM engine|non-default args"), "initializing"),
    (re.compile(r"Starting to load model|Loading weights|Loading safetensors"), "loading weights"),
    # vLLM's memory profiling run; on a first start Triton autotunes kernels here (minutes for hybrid models)
    (re.compile(r"Model loading took"), "profiling"),
    (re.compile(r"torch\.compile took|Compiling a graph|Dynamo bytecode transform"), "compiling"),
    (re.compile(r"Capturing CUDA graphs"), "capturing graphs"),
    (re.compile(r"Available KV cache memory|GPU KV cache size"), "allocating KV cache"),
    (re.compile(r"JIT kernel warmup \("), "warming up"),
    (re.compile(r"Starting vLLM API server|Application startup complete"), "starting server"),
]
STAGE_ORDER = ["starting container", "initializing", "loading weights", "profiling", "compiling", "capturing graphs",
               "allocating KV cache", "warming up", "starting server"]


def next_stage(current: str | None, line: str) -> str | None:
    """Stages only move forward: a later line that mentions an earlier milestone doesn't go back."""
    for rx, stage in STAGES:
        if rx.search(line) and (current not in STAGE_ORDER or STAGE_ORDER.index(stage) >= STAGE_ORDER.index(current)):
            current = stage
    return current


class EngineError(Exception):
    def __init__(self, status: int, code: str, detail: str, data: dict[str, Any] | None = None):
        super().__init__(detail)
        self.status, self.code, self.detail, self.data = status, code, detail, data or {}


class Engine:
    def __init__(self, settings: Settings, hub: Hub, containers: Podman | FakeContainers | None = None,
                 gtt_total: int | None = None, poll_s: float = 0.5):
        self.s = settings
        self.hub = hub
        self.c = containers or (FakeContainers(settings.state_dir) if settings.fake else Podman(settings.podman))
        self.gtt_total = gtt_total or gtt_total_bytes()
        self.poll_s = poll_s
        self.state = "unloaded"
        self.profile: Profile | None = None
        self.stage: str | None = None
        self.error: str | None = None
        self.last_error: str | None = None
        self.command: list[str] = []
        self.started_at: float | None = None
        self.ready_at: float | None = None
        self.failed_at: float | None = None
        self.lines: deque[str] = deque(maxlen=500)
        self.before_start: list[Hook] = []      # downloads (18.3)
        self.on_ready: list[Hook] = []          # relay publishing (18.4)
        self.on_stopping: list[Hook] = []
        self._lock = asyncio.Lock()
        self._done = asyncio.Event()
        self._tasks: list[asyncio.Task] = []
        self.http = httpx.AsyncClient(base_url=f"http://127.0.0.1:{settings.engine_port}", timeout=5)

    # profiles ---------------------------------------------------------------------------------

    def profiles(self) -> dict[str, Profile]:
        return load_profiles(self.s.profiles_dir)[0]

    @property
    def _last_file(self):
        return self.s.state_dir / "last.json"

    def last_profile(self) -> str | None:
        try:
            return json.loads(self._last_file.read_text()).get("profile")
        except (OSError, ValueError):
            return None

    def default_profile(self) -> Profile | None:
        """The current profile, else the last loaded, else the first."""
        if self.profile:
            return self.profile
        found = self.profiles()
        return found.get(self.last_profile() or "") or next(iter(found.values()), None)

    def needs_gb(self, p: Profile) -> float:
        return p.memory_gb + self.s.overhead_gb

    # load / unload ----------------------------------------------------------------------------

    async def load(self, profile_id: str | None = None, make_room: bool = False, wait: bool = True) -> dict[str, Any]:
        found = self.profiles()
        pid = profile_id or (self.profile.id if self.profile else None) or self.last_profile() or next(iter(found), None)
        if not pid or pid not in found:
            raise EngineError(404, "not_found", f"no profile {pid!r}" if pid else "no profiles in profiles/",
                              {"profiles": list(found)})
        p = found[pid]
        async with self._lock:
            if self.profile and self.profile.id == pid and self.state in ("starting", "ready"):
                done = self._done
            else:
                if self.state in ("starting", "ready", "failed"):
                    await self._stop(reason=f"switching to {pid}")
                done = await self._start(p, make_room)
        if wait:
            await done.wait()
            if self.state != "ready":
                raise EngineError(500, "start_failed", self.last_error or f"{p.name} didn't start",
                                  {"log": list(self.lines)[-30:]})
        return self.view()

    async def _start(self, p: Profile, make_room: bool) -> asyncio.Event:
        self.profile, self.state, self.stage, self.error = p, "starting", "preparing", None
        self.started_at, self.ready_at, self.lines = time.time(), None, deque(maxlen=500)
        self._done = done = asyncio.Event()
        try:
            for hook in self.before_start:
                await hook(p)
            self.stage = "waiting for memory"
            await self.hub.acquire(self.needs_gb(p), f"vLLM {p.name}", make_room)
            self.command = engine_command(p, self.s, self.gtt_total)
            (self.s.cache_dir).mkdir(parents=True, exist_ok=True)
            self.s.hf_home.mkdir(parents=True, exist_ok=True)
            await self.c.remove(p.container)            # a leftover with the same name
            self.stage = "starting container"
            log.info("starting %s: %s", p.container, " ".join(self.command))
            await self.c.run(self.command)
        except Exception as e:
            self.state, self.profile, self.stage = "unloaded", None, None
            self.last_error = str(e)
            done.set()
            if isinstance(e, (EngineError, NeedsRoom)):
                raise
            raise EngineError(500, "start_failed", f"podman: {e}" if isinstance(e, ContainerError) else str(e)) from e
        self._last_file.write_text(json.dumps({"profile": p.id}))
        self._watch(p, adopted=False)
        return done

    async def unload(self) -> dict[str, Any]:
        async with self._lock:
            if self.state != "unloaded":
                await self._stop(reason="unload")
        return self.view()

    async def _stop(self, reason: str) -> None:
        p = self.profile
        was = self.state
        self.state, self.stage = "stopping", None
        if p and was == "ready":
            await self._hooks(self.on_stopping, p)
        await self._cancel_tasks()
        if p:
            log.info("stopping %s (%s)", p.container, reason)
            with suppress(ContainerError):
                await self.c.stop(p.container, timeout=30)
            with suppress(ContainerError):
                await self.c.remove(p.container)
            await self._hooks(self.on_stopping, p)       # again once it's gone (idempotent)
        self.state, self.profile, self.ready_at = "unloaded", None, None
        self._done.set()

    async def _hooks(self, hooks: list[Hook], p: Profile) -> None:
        for hook in hooks:
            try:
                await hook(p)
            except Exception:  # noqa: BLE001
                log.exception("hook %s failed", getattr(hook, "__name__", hook))

    # watching ---------------------------------------------------------------------------------

    def _watch(self, p: Profile, adopted: bool) -> None:
        self._tasks = [asyncio.create_task(self._follow(p, adopted)), asyncio.create_task(self._monitor(p))]

    async def _follow(self, p: Profile, adopted: bool) -> None:
        """The engine's log: into the adapter's stdout (AIHub's Logs tab), the ring, and the stage."""
        try:
            async for line in self.c.logs(p.container, tail=200 if adopted else None):
                self.lines.append(line)
                print(f"engine: {line}", flush=True)
                if self.state == "starting":
                    self.stage = next_stage(self.stage, line)
        except ContainerError as e:
            log.warning("log follower: %s", e)

    async def _monitor(self, p: Profile) -> None:
        deadline = time.time() + self.s.start_timeout_s       # from the container's start, not the download
        last_check = 0.0
        while self.state in ("starting", "ready"):
            await asyncio.sleep(self.poll_s)
            now = time.monotonic()
            if self.state == "starting" and await self._healthy():
                self.state, self.stage, self.ready_at = "ready", None, time.time()
                log.info("%s is ready after %.0fs", p.name, self.ready_at - (self.started_at or self.ready_at))
                self._done.set()
                await self._hooks(self.on_ready, p)
                continue
            if now - last_check >= 4 * self.poll_s:
                last_check = now
                st = await self.c.state(p.container)
                if st != "running" and self.state in ("starting", "ready"):
                    await asyncio.sleep(0.3)                 # let the follower read the last lines
                    await self._fail(p, f"vLLM exited ({'while starting' if self.state == 'starting' else 'while serving'})")
                    return
            if self.state == "starting" and time.time() > deadline:
                await self._fail(p, f"vLLM wasn't healthy after {self.s.start_timeout_s:.0f}s", stop=True)
                return

    async def _healthy(self) -> bool:
        try:
            return (await self.http.get("/health")).status_code == 200
        except httpx.HTTPError:
            return False

    async def _fail(self, p: Profile, why: str, stop: bool = False) -> None:
        was_ready = self.state == "ready"
        tail = "\n".join(list(self.lines)[-30:])
        self.last_error = f"{why}\n{tail}".strip()
        log.error("%s: %s", p.name, why)
        self.state, self.stage, self.error, self.failed_at = "failed", None, why, time.time()
        if was_ready:
            await self._hooks(self.on_stopping, p)
        with suppress(ContainerError):
            if stop:
                await self.c.stop(p.container, timeout=10)
            await self.c.remove(p.container)
        self._done.set()

    async def _cancel_tasks(self) -> None:
        current = asyncio.current_task()
        for t in self._tasks:
            if t is not current:
                t.cancel()
                with suppress(asyncio.CancelledError, Exception):
                    await t
        self._tasks = []

    # adapter start and stop -------------------------------------------------------------------

    async def adopt(self) -> None:
        """Take over an engine left running by a previous adapter; remove anything else of ours."""
        found = self.profiles()
        for f in await self.c.list():
            if f.running and self.profile is None and f.profile in found:
                p = found[f.profile]
                log.info("adopting %s", f.name)
                self.profile, self.state, self.stage = p, "starting", "adopting"
                self.started_at = time.time()
                self.command = engine_command(p, self.s, self.gtt_total)
                self._done = asyncio.Event()
                self._watch(p, adopted=True)
            else:
                log.info("removing leftover %s", f.name)
                with suppress(ContainerError):
                    await self.c.remove(f.name)

    async def shutdown(self, stop_engine: bool = True) -> None:
        """The adapter is stopping: stop the engine too (stopping the mod is how memory is freed).
        `stop_engine=False` only lets go of it, as a crash would."""
        if stop_engine and self.state != "unloaded":
            async with self._lock:
                await self._stop(reason="the adapter is stopping")
        else:
            await self._cancel_tasks()
        await self.http.aclose()

    # views ------------------------------------------------------------------------------------

    def view(self) -> dict[str, Any]:
        p = self.profile
        return {
            "state": self.state, "profile": p.id if p else None, "name": p.name if p else None,
            "served_name": p.served if p else None, "stage": self.stage, "error": self.error,
            "last_error": self.last_error, "started_at": self.started_at, "ready_at": self.ready_at,
            "endpoint": f"http://127.0.0.1:{self.s.engine_port}/v1" if self.state == "ready" else None,
            "command": self.command if p else [], "memory_gb": self.needs_gb(p) if p else None,
        }
