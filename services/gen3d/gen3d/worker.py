"""The GPU workers: a `podman run -i` of the ROCm image running one worker script (or, for the cuda variant,
the script itself on the host, in its venv: plan 39.7).

Each engine family has its own venv and script (SPECS): `cube` (Cube3D + CubePart, workers/cube_worker.py),
`img3d` (Hunyuan3D 2.1) and `sam3do` (SAM 3D Objects). Only one container runs at a time: the pool
stops the running one before another starts. Stopping the container is the unload: it hands back
every byte of GPU memory. Cancelling a running job also stops it (a GPU call cannot be interrupted
any other way); the next job starts a new one.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import logging
import os
import signal
import time

from .config import ROOT, settings

log = logging.getLogger("gen3d.worker")
NAME_PREFIX = "gen3d-worker-"
_seq = itertools.count(1)


class WorkerError(RuntimeError):
    pass


def specs() -> dict[str, dict]:
    """Per family: the venv, the script, its PYTHONPATH, extra environment and the cache folder."""
    rt, workers = settings.runtime, ROOT / "workers"
    ca = settings.cubeart
    return {
        "cube": {"venv": ca / ".venv", "script": workers / "cube_worker.py", "cache": ca / ".cache", "hf": ca / "hf_cache",
                 "pythonpath": [ca / "cube" / "cubepart", ca / "cube", workers], "mount": ca, "env": {}},
        "img3d": {"venv": rt / "img3d" / ".venv", "script": workers / "hunyuan_worker.py", "cache": rt / "img3d" / ".cache",
                  "pythonpath": [rt / "hunyuan3d-2.1" / "hy3dshape", workers], "mount": rt,
                  "env": {"GEN3D_RUNTIME": str(rt)}},
        "sam3do": {"venv": rt / "sam3do" / ".venv", "script": workers / "sam3do_worker.py", "cache": rt / "sam3do" / ".cache",
                   "pythonpath": [workers / "shims", rt / "sam3d-objects", workers], "mount": rt,
                   "env": {"GEN3D_RUNTIME": str(rt), "LIDRA_SKIP_INIT": "true"}},
    }


class CubeWorker:
    def __init__(self, family: str = "cube") -> None:
        self.family = family
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
        return {"state": self.state, "loaded": sorted(self.loaded), "container": self.name, "family": self.family,
                "device": self.info.get("device"), "torch": self.info.get("torch"),
                "uptime_s": round(time.time() - self.started_at, 1) if self.started_at and self.up else None}

    @property
    def native(self) -> bool:
        """The cuda variant runs the worker on the host (plan 39.7); rocm in the image."""
        return settings.accel != "rocm"

    def native_command(self) -> tuple[list[str], dict[str, str]]:
        """The worker script in its venv on the host, and its environment: the container's, without ROCm's."""
        sp = specs()[self.family]
        cache = str(sp["cache"])
        env = {
            "GEN3D_CUBEART": str(settings.cubeart), "GEN3D_WEIGHTS": str(settings.weights.resolve()), "HF_HUB_OFFLINE": "1",
            "HF_HOME": str(sp.get("hf") or f"{cache}/hf"), "XDG_CACHE_HOME": cache, "TORCHINDUCTOR_CACHE_DIR": f"{cache}/inductor",
            "TORCH_HOME": f"{cache}/torch", "TRITON_CACHE_DIR": f"{cache}/triton", "TMPDIR": f"{cache}/tmp",
            "PYTORCH_CUDA_ALLOC_CONF": "expandable_segments:True",
            "PYTHONPATH": ":".join(str(p) for p in sp["pythonpath"]), "PYTHONUNBUFFERED": "1", **sp["env"],
        }
        script = f"mkdir -p {cache}/tmp; source {sp['venv']}/bin/activate && exec python -u {sp['script']}"
        return ["bash", "-c", script], env

    def command(self) -> list[str]:
        # Mount real paths, never symlinks: a link that points outside its mount is broken inside
        # the container (AIHub architecture §12.3). The jobs folder is the only writable mount
        # besides the family's code/venv/cache folder.
        sp = specs()[self.family]
        ca, jobs, workers = str(settings.cubeart), str(settings.jobs_dir.resolve()), str(ROOT / "workers")
        mount, cache = str(sp["mount"]), str(sp["cache"])
        weights = str(settings.weights.resolve())
        env = {
            "GEN3D_CUBEART": ca, "GEN3D_WEIGHTS": weights, "HF_HUB_OFFLINE": "1", "HF_HOME": str(sp.get("hf") or f"{cache}/hf"),
            "XDG_CACHE_HOME": cache, "TORCHINDUCTOR_CACHE_DIR": f"{cache}/inductor", "TORCH_HOME": f"{cache}/torch",
            "TRITON_CACHE_DIR": f"{cache}/triton", "MIOPEN_USER_DB_PATH": f"{cache}/miopen", "TMPDIR": f"{cache}/tmp",
            "PYTORCH_HIP_ALLOC_CONF": "expandable_segments:True", "TORCH_ROCM_AOTRITON_ENABLE_EXPERIMENTAL": "1",
            # rocprofiler-sdk attaches to every process and polls its queues; nothing here profiles.
            "ROCPROFILER_REGISTER_ENABLED": "0",
            "PYTHONPATH": ":".join(str(p) for p in sp["pythonpath"]), "PYTHONUNBUFFERED": "1", **sp["env"],
        }
        cmd = [settings.podman, "run", "--rm", "-i", "--name", self.name, "--network", "none", "--ipc", "host",
               "--device", "/dev/kfd", "--device", "/dev/dri", "--group-add", "keep-groups",
               "--security-opt", "label=disable", "--security-opt", "seccomp=unconfined",
               "-v", f"{mount}:{mount}", "-v", f"{jobs}:{jobs}", "-v", f"{workers}:{workers}:ro", "-w", workers]
        if not weights.startswith(mount.rstrip("/") + "/"):
            cmd[cmd.index("-w"):cmd.index("-w")] = ["-v", f"{weights}:{weights}:ro"]
        for k, v in env.items():
            cmd += ["-e", f"{k}={v}"]
        script = (f"unset HSA_OVERRIDE_GFX_VERSION; mkdir -p {cache}/tmp; source {sp['venv']}/bin/activate && "
                  f"exec python -u {sp['script']}")
        return cmd + [settings.image, "bash", "-c", script]

    async def _cleanup_stale(self) -> None:
        """A server that crashed can leave a worker container holding GPU memory: remove it."""
        if self._cleaned or self.native:
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
        self.name = f"{NAME_PREFIX}{self.family}-{os.getpid()}-{next(_seq)}"
        self.state = "starting"
        t0 = time.time()
        if on_event:
            on_event({"event": "sub", "sub": "worker.start"})
        if self.native:
            argv, extra = self.native_command()
            log.info("starting worker %s on the host (%s)", self.name, settings.accel)
            self.proc = await asyncio.create_subprocess_exec(
                *argv, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=None, limit=1 << 22,
                start_new_session=True, cwd=str(ROOT / "workers"), env={**os.environ, **extra})
        else:
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
        if self.native:
            if self.proc and self.proc.returncode is None:
                try:
                    os.killpg(self.proc.pid, signal.SIGKILL)     # the worker and anything it started
                except ProcessLookupError:
                    pass
            self.state, self.loaded = "stopped", set()
            return
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


class WorkerPool:
    """One worker container per engine family, at most one running: the runner talks to this as it did
    to the single Cube3D worker. A run in another family stops the running container first, so its
    memory is back before the next one loads."""

    def __init__(self, make=CubeWorker) -> None:
        self._make = make
        self.workers: dict[str, object] = {}
        self.active = "cube"
        self._switch = asyncio.Lock()

    def get(self, family: str):
        if family not in self.workers:
            self.workers[family] = self._make(family)
        return self.workers[family]

    @property
    def current(self):
        return self.get(self.active)

    @property
    def up(self) -> bool:
        return any(w.up for w in self.workers.values())

    @property
    def loaded(self) -> set[str]:
        return set().union(*(w.loaded for w in self.workers.values() if w.up)) if self.workers else set()

    def status(self) -> dict:
        w = next((w for w in self.workers.values() if w.up), None) or self.current
        return w.status()

    async def use(self, family: str):
        """The family's worker, after stopping any other that is running."""
        async with self._switch:
            for name, w in self.workers.items():
                if name != family and w.up:
                    await w.stop(reason=f"switching to {family}")
            self.active = family
            return self.get(family)

    async def run(self, task: dict, on_event, cancel_check=lambda: False) -> dict:
        w = await self.use(task.get("family") or "cube")
        return await w.run(task, on_event, cancel_check)

    async def load(self, models: list[str]) -> None:
        await (await self.use("cube")).load(models)

    async def cancel(self) -> None:
        for w in self.workers.values():
            if w.up or w.state != "stopped":
                await w.cancel()

    async def stop(self, reason: str = "", graceful: bool = True) -> bool:
        stopped = False
        for w in self.workers.values():
            stopped = await w.stop(reason=reason, graceful=graceful) or stopped
        return stopped
