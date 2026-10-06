"""The GPU worker: a `podman run -i` of the ROCm image running workers/cube_worker.py.

Stopping the container is the unload: it hands back every byte of GPU memory. Cancelling a running
job also stops it (a GPU call cannot be interrupted any other way); the next job starts a new one.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import logging
import os
import time

from .config import ROOT, settings

log = logging.getLogger("gen3d.worker")
NAME_PREFIX = "gen3d-worker-"
_seq = itertools.count(1)


class WorkerError(RuntimeError):
    pass


class CubeWorker:
    def __init__(self) -> None:
        self.proc: asyncio.subprocess.Process | None = None
        self.name: str | None = None
        self.state = "stopped"      # stopped | starting | ready | busy
        self.loaded: set[str] = set()
        self.info: dict = {}
        self.started_at: float | None = None
        self._lock = asyncio.Lock()
        self._cleaned = False

    @property
    def up(self) -> bool:
        return self.proc is not None and self.proc.returncode is None and self.state in ("ready", "busy")

    def status(self) -> dict:
        return {"state": self.state, "loaded": sorted(self.loaded), "container": self.name,
                "device": self.info.get("device"), "torch": self.info.get("torch"),
                "uptime_s": round(time.time() - self.started_at, 1) if self.started_at and self.up else None}

    def command(self) -> list[str]:
        # Mount real paths, never symlinks: a link that points outside its mount is broken inside
        # the container (AIHub architecture §12.3). The jobs folder is the only writable mount
        # besides CubeArt's own caches.
        ca, jobs, workers = str(settings.cubeart), str(settings.jobs_dir.resolve()), str(ROOT / "workers")
        weights = str(settings.weights.resolve())
        env = {
            "GEN3D_CUBEART": ca, "GEN3D_WEIGHTS": weights, "HF_HUB_OFFLINE": "1", "HF_HOME": f"{ca}/hf_cache",
            "XDG_CACHE_HOME": f"{ca}/.cache", "TORCHINDUCTOR_CACHE_DIR": f"{ca}/.cache/inductor",
            "TRITON_CACHE_DIR": f"{ca}/.cache/triton", "MIOPEN_USER_DB_PATH": f"{ca}/.cache/miopen",
            "PYTORCH_HIP_ALLOC_CONF": "expandable_segments:True", "TORCH_ROCM_AOTRITON_ENABLE_EXPERIMENTAL": "1",
            # rocprofiler-sdk attaches to every process and polls its queues; nothing here profiles.
            "ROCPROFILER_REGISTER_ENABLED": "0",
            "PYTHONPATH": f"{ca}/cube/cubepart:{ca}/cube:{workers}", "PYTHONUNBUFFERED": "1",
        }
        cmd = [settings.podman, "run", "--rm", "-i", "--name", self.name, "--network", "none", "--ipc", "host",
               "--device", "/dev/kfd", "--device", "/dev/dri", "--group-add", "keep-groups",
               "--security-opt", "label=disable", "--security-opt", "seccomp=unconfined",
               "-v", f"{ca}:{ca}", "-v", f"{jobs}:{jobs}", "-v", f"{workers}:{workers}:ro", "-w", workers]
        if not weights.startswith(ca.rstrip("/") + "/"):
            cmd[cmd.index("-w"):cmd.index("-w")] = ["-v", f"{weights}:{weights}:ro"]
        for k, v in env.items():
            cmd += ["-e", f"{k}={v}"]
        script = (f"unset HSA_OVERRIDE_GFX_VERSION; source {ca}/.venv/bin/activate && "
                  f"exec python -u {workers}/cube_worker.py")
        return cmd + [settings.image, "bash", "-c", script]

    async def _cleanup_stale(self) -> None:
        """A server that crashed can leave a worker container holding GPU memory: remove it."""
        if self._cleaned:
            return
        self._cleaned = True
        p = await asyncio.create_subprocess_exec(settings.podman, "ps", "-aq", "--filter", f"name={NAME_PREFIX}",
                                                 stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        out, _ = await p.communicate()
        ids = out.decode().split()
        if ids:
            log.warning("removing %d stale worker container(s)", len(ids))
            await (await asyncio.create_subprocess_exec(settings.podman, "rm", "-f", *ids,
                                                        stdout=asyncio.subprocess.DEVNULL,
                                                        stderr=asyncio.subprocess.DEVNULL)).wait()

    async def _read(self) -> dict:
        assert self.proc and self.proc.stdout
        while True:
            line = await self.proc.stdout.readline()
            if not line:
                code = await self.proc.wait()
                self.state, self.loaded = "stopped", set()
                raise WorkerError(f"worker exited (code {code}); see `gen3d logs`")
            try:
                return json.loads(line)
            except ValueError:
                log.info("[worker] %s", line.decode(errors="replace").rstrip())

    async def _send(self, msg: dict) -> None:
        assert self.proc and self.proc.stdin
        self.proc.stdin.write((json.dumps(msg) + "\n").encode())
        await self.proc.stdin.drain()

    async def start(self, on_event=None) -> None:
        if self.up:
            return
        await self._cleanup_stale()
        self.name = f"{NAME_PREFIX}{os.getpid()}-{next(_seq)}"
        self.state = "starting"
        t0 = time.time()
        if on_event:
            on_event({"event": "sub", "sub": "worker.start"})
        log.info("starting worker container %s", self.name)
        self.proc = await asyncio.create_subprocess_exec(
            *self.command(), stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=None, limit=1 << 22, start_new_session=True)
        try:
            msg = await asyncio.wait_for(self._read(), settings.load_timeout_s)
        except Exception:
            await self.stop(reason="failed to start")
            raise
        if msg.get("event") != "ready":
            await self.stop(reason="failed to start")
            raise WorkerError(f"worker failed to start: {msg}")
        self.info = msg
        self.state, self.started_at = "ready", time.time()
        log.info("worker ready in %.1fs (%s, torch %s)", time.time() - t0, msg.get("device"), msg.get("torch"))
        if on_event:
            on_event({"event": "sub_done", "sub": "worker.start", "seconds": time.time() - t0})

    async def load(self, models: list[str]) -> None:
        async with self._lock:
            await self.start()
            self.state = "busy"
            try:
                await self._send({"cmd": "load", "models": models})
                while True:
                    msg = await self._read()
                    if msg.get("event") == "loaded":
                        self.loaded = set(msg["models"])
                        return
                    if msg.get("event") == "error":
                        raise WorkerError(msg["message"])
            finally:
                if self.state == "busy":
                    self.state = "ready"

    async def run(self, task: dict, on_event, cancel_check=lambda: False) -> dict:
        async with self._lock:
            await self.start(on_event)
            self.state = "busy"
            try:
                await self._send({"cmd": "run", "task": task})
                while True:
                    msg = await self._read()
                    ev = msg.get("event")
                    if ev in ("sub", "progress", "sub_done"):
                        if ev == "sub_done" and msg["sub"].startswith("load."):
                            self.loaded.add(msg["sub"].split(".", 1)[1])
                        on_event(msg)
                    elif ev == "result":
                        self.loaded = set(msg.get("loaded", self.loaded))
                        return msg["result"]
                    elif ev == "error":
                        self.loaded = set(msg.get("loaded", self.loaded))
                        log.error("worker error: %s\n%s", msg["message"], msg.get("trace", ""))
                        raise WorkerError(msg["message"])
            finally:
                if self.state == "busy":
                    self.state = "ready"

    async def cancel(self) -> None:
        """Abort whatever is running by stopping the container (the lock holder then sees EOF)."""
        await self._kill()

    async def _kill(self) -> None:
        if self.name:
            p = await asyncio.create_subprocess_exec(settings.podman, "kill", self.name,
                                                     stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
            await p.wait()
        if self.proc and self.proc.returncode is None:
            try:
                self.proc.kill()
            except ProcessLookupError:
                pass
        self.state, self.loaded = "stopped", set()

    async def stop(self, reason: str = "", graceful: bool = True) -> bool:
        """graceful=False kills at once: a worker in the middle of a GPU call cannot read "quit"."""
        if not self.proc or self.proc.returncode is not None:
            self.state, self.loaded = "stopped", set()
            return False
        log.info("stopping worker (%s)", reason)
        try:
            if graceful and self.state != "busy":
                await self._send({"cmd": "quit"})
                await asyncio.wait_for(self.proc.wait(), 20)
        except Exception:
            pass
        if self.proc.returncode is None:
            await self._kill()
            try:
                await asyncio.wait_for(self.proc.wait(), 20)
            except asyncio.TimeoutError:
                log.warning("worker container %s did not exit", self.name)
        self.state, self.loaded, self.started_at = "stopped", set(), None
        return True
