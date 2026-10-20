"""The sandbox (plan 27.5): commands in a rootless podman container, each run kept as a record.

- **The image** (`sandbox/Containerfile`): only Python 3.12, uv, Node LTS, git, ripgrep,
  build-essential and the data libraries; base images pinned by digest. Built as
  `localhost/aihub-workspace-sandbox:<VERSION>` from the Workspace page (`POST /v1/sandbox/build`).
- **A run:** your user inside (`--userns=keep-id`), the folder mounted read-write **at the same
  absolute path** (read-only below Run), `~/.cache/uv`, `~/.cache/pip` and `~/.npm` as overlays
  (read from, never written back), the rest of `$HOME` a fresh tmpfs, a read-only root, no network
  unless asked for (Run + network: full internet), memory and process limits, a timeout (120 s by
  default, 600 s at most). SELinux labels are left alone (`label=disable`) rather than relabelling
  your folder.
- **Records:** `$WORKSPACE_STATE/runs/<id>.json` with the command, where, exit code, timing and the
  last 32 KB of stdout and stderr; the whole output in `<id>.out` / `<id>.err` (1 MB each kept).
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import shlex
import shutil
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
VERSION = "1"
IMAGE = f"localhost/aihub-workspace-sandbox:{VERSION}"
DEFAULT_TIMEOUT, MAX_TIMEOUT = 120, 600
MEMORY, PIDS = "8g", 1024
KEEP_BYTES = 1024 * 1024
TAIL = 32 * 1024
CACHES = (".cache/uv", ".cache/pip", ".npm")
TOOLCHAIN = "Python 3.12, uv, Node LTS, git, ripgrep and build tools"


@dataclass
class Run:
    id: str
    command: str
    where: str                        # sandbox | host
    cwd: str | None
    network: bool = False
    writable: bool = True
    folder: str | None = None
    thread: str | None = None
    turn: str | None = None
    timeout_s: int = DEFAULT_TIMEOUT
    state: str = "running"            # running | done | timeout | cancelled | error
    exit_code: int | None = None
    started: float = field(default_factory=time.time)
    finished: float | None = None
    ms: int | None = None
    stdout: str = ""
    stderr: str = ""
    truncated: bool = False
    note: str | None = None
    outputs: list[str] = field(default_factory=list)

    def public(self) -> dict[str, Any]:
        return asdict(self)


def new_id() -> str:
    return "run_" + time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3)


class Records:
    def __init__(self, state: Path) -> None:
        self.dir = state / "runs"

    def save(self, r: Run) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self.dir / f".{r.id}.json"
        tmp.write_text(json.dumps(r.public()))
        os.replace(tmp, self.dir / f"{r.id}.json")

    def get(self, rid: str) -> dict[str, Any] | None:
        if not rid.replace("_", "").replace("-", "").isalnum():
            return None
        try:
            return json.loads((self.dir / f"{rid}.json").read_text())
        except (OSError, ValueError):
            return None

    def list(self, thread: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        if not self.dir.is_dir():
            return []
        out = []
        for p in sorted(self.dir.glob("run_*.json"), reverse=True):
            try:
                r = json.loads(p.read_text())
            except (OSError, ValueError):
                continue
            if thread and r.get("thread") != thread:
                continue
            out.append({k: v for k, v in r.items() if k not in ("stdout", "stderr")})
            if len(out) >= limit:
                break
        return out

    def prune(self, keep: int = 2000) -> None:
        files = sorted(self.dir.glob("run_*.json")) if self.dir.is_dir() else []
        for p in files[:-keep] if len(files) > keep else []:
            for f in (p, p.with_suffix(".out"), p.with_suffix(".err")):
                f.unlink(missing_ok=True)


async def _pump(stream: asyncio.StreamReader, path: Path) -> tuple[str, bool]:
    """Copy a stream to `path` (the first 1 MB) and keep its last 32 KB."""
    kept, tail, cut = 0, bytearray(), False
    with path.open("wb") as f:
        while True:
            chunk = await stream.read(65536)
            if not chunk:
                break
            if kept < KEEP_BYTES:
                f.write(chunk[: KEEP_BYTES - kept])
                kept += min(len(chunk), KEEP_BYTES - kept)
            else:
                cut = True
            tail += chunk
            if len(tail) > TAIL:
                del tail[: len(tail) - TAIL]
                cut = True
    return tail.decode("utf-8", errors="replace"), cut


class Sandbox:
    def __init__(self, state: Path, image: str = IMAGE, podman: str = "podman", home: Path | None = None) -> None:
        self.state, self.image_name, self.podman = state, image, podman
        self.home = home or Path.home()
        self.records = Records(state)
        self.live: dict[str, asyncio.subprocess.Process] = {}
        self.cancelled: set[str] = set()
        self.building: asyncio.Task[Any] | None = None
        self.build_log = state / "sandbox-build.log"

    # ---- the image ------------------------------------------------------------------------

    def available(self) -> bool:
        return shutil.which(self.podman) is not None

    async def _podman(self, *args: str, timeout: float = 30) -> tuple[int, str, str]:
        p = await asyncio.create_subprocess_exec(self.podman, *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            out, err = await asyncio.wait_for(p.communicate(), timeout)
        except asyncio.TimeoutError:
            p.kill()
            return 124, "", "timed out"
        return p.returncode or 0, out.decode(errors="replace"), err.decode(errors="replace")

    async def image(self) -> dict[str, Any]:
        info: dict[str, Any] = {"image": self.image_name, "podman": self.available(), "exists": False,
                                "building": bool(self.building and not self.building.done()), "toolchain": TOOLCHAIN,
                                "containerfile": str(HERE / "sandbox" / "Containerfile")}
        if not info["podman"]:
            info["why"] = "podman isn't installed"
            return info
        rc, out, _ = await self._podman("image", "inspect", self.image_name, "--format", "{{json .}}")
        if rc == 0 and out.strip():
            j = json.loads(out)
            info.update({"exists": True, "id": j.get("Id", "")[:12], "digest": j.get("Digest"), "created": j.get("Created"),
                         "size_mb": round((j.get("Size") or 0) / 1e6)})
        if self.build_log.exists():
            info["build_log_tail"] = self.build_log.read_text(errors="replace")[-2000:]
        return info

    async def build(self) -> dict[str, Any]:
        """Start building the image (minutes; it downloads the base images and libraries)."""
        if self.building and not self.building.done():
            return {"state": "building"}
        self.state.mkdir(parents=True, exist_ok=True)

        async def go() -> int:
            with self.build_log.open("w") as log:
                p = await asyncio.create_subprocess_exec(self.podman, "build", "-t", self.image_name, "-f",
                                                         str(HERE / "sandbox" / "Containerfile"), str(HERE / "sandbox"),
                                                         stdout=log, stderr=asyncio.subprocess.STDOUT)
                return await p.wait()
        self.building = asyncio.create_task(go())
        return {"state": "building", "log": str(self.build_log)}

    # ---- runs -------------------------------------------------------------------------------

    def argv(self, run: Run, cwd: Path, mounts: list[tuple[Path, str]], env: dict[str, str]) -> list[str]:
        """The podman command line for a run: `mounts` are (path, "rw" | "ro"), each at its own path."""
        name = f"aihub-ws-{run.id}"
        home = str(self.home)
        args = [self.podman, "run", "--rm", "--name", name, "--userns=keep-id", "--security-opt", "label=disable",
                "--read-only", f"--memory={MEMORY}", f"--memory-swap={MEMORY}", f"--pids-limit={PIDS}",
                "--network=" + ("pasta" if run.network else "none"),
                "--tmpfs", "/tmp:rw,size=2g,mode=1777", "--tmpfs", f"{home}:rw,size=2g,mode=0777",
                "--label", "aihub.workspace=1"]
        for rel in CACHES:
            src = self.home / rel
            if src.is_dir():
                args += ["-v", f"{src}:{src}:O"]
        for path, mode in mounts:
            args += ["-v", f"{path}:{path}:{'rw' if mode == 'rw' else 'ro'}"]
        for k, v in {"HOME": home, **env}.items():
            args += ["-e", f"{k}={v}"]
        args += ["-w", str(cwd), self.image_name, "bash", "-c", run.command]
        return args

    async def run(self, run: Run, cwd: Path, mounts: list[tuple[Path, str]], env: dict[str, str] | None = None,
                  disconnected: Any = None) -> Run:
        """Run in the sandbox; `disconnected()`: an awaitable check that cancels the run when the caller left."""
        info = await self.image()
        if not info["exists"]:
            raise SandboxMissing(info.get("why") or f"the sandbox image {self.image_name} isn't built yet")
        argv = self.argv(run, cwd, mounts, env or {})
        return await self._exec(run, argv, disconnected, container=f"aihub-ws-{run.id}")

    async def run_host(self, run: Run, cwd: Path, disconnected: Any = None) -> Run:
        """On this machine, outside the sandbox (plan 27.6): only after the user allowed this one call."""
        return await self._exec(run, ["bash", "-c", run.command], disconnected, cwd=cwd)

    async def _exec(self, run: Run, argv: list[str], disconnected: Any, container: str | None = None,
                    cwd: Path | None = None) -> Run:
        self.records.save(run)
        self.records.dir.mkdir(parents=True, exist_ok=True)
        p = await asyncio.create_subprocess_exec(*argv, cwd=cwd, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
                                                 stderr=asyncio.subprocess.PIPE, start_new_session=True)
        self.live[run.id] = p
        out_t = asyncio.create_task(_pump(p.stdout, self.records.dir / f"{run.id}.out"))   # type: ignore[arg-type]
        err_t = asyncio.create_task(_pump(p.stderr, self.records.dir / f"{run.id}.err"))   # type: ignore[arg-type]
        deadline = time.time() + run.timeout_s
        try:
            while True:
                try:
                    await asyncio.wait_for(asyncio.shield(p.wait()), timeout=0.5)
                    break
                except asyncio.TimeoutError:
                    pass
                if run.id in self.cancelled:
                    run.state = "cancelled"
                    break
                if time.time() > deadline:
                    run.state = "timeout"
                    break
                if disconnected is not None and await disconnected():
                    run.state = "cancelled"
                    run.note = "the caller went away (the call was cancelled)"
                    break
            if p.returncode is None:
                await self._stop(p, container)
        except asyncio.CancelledError:
            run.state = "cancelled"
            await self._stop(p, container)
            raise
        finally:
            (run.stdout, c1), (run.stderr, c2) = await asyncio.gather(out_t, err_t)
            run.truncated = c1 or c2
            run.exit_code = p.returncode if run.state not in ("timeout", "cancelled") else None
            if run.id in self.cancelled:
                run.state, run.exit_code = "cancelled", None
                run.note = run.note or "cancelled"
                self.cancelled.discard(run.id)
            if run.state == "running":
                run.state = "done"
            run.finished = time.time()
            run.ms = int((run.finished - run.started) * 1000)
            if run.state == "timeout":
                run.note = f"stopped after {run.timeout_s} s (the timeout; pass timeout_s up to {MAX_TIMEOUT})"
            elif run.where == "sandbox" and run.exit_code in (126, 127) and ("not found" in run.stderr or "No such file" in run.stderr):
                run.note = (f"a program isn't in the sandbox (it has {TOOLCHAIN}); install it into the folder (Run + network), "
                            "or run it on the user's machine with where=\"host\", which asks them")
            self.live.pop(run.id, None)
            self.records.save(run)
            self.records.prune()
        return run

    async def _stop(self, p: asyncio.subprocess.Process, container: str | None) -> None:
        if container:
            await self._podman("kill", container, timeout=15)
        else:
            try:
                os.killpg(p.pid, 9)
            except ProcessLookupError:
                pass
        try:
            await asyncio.wait_for(p.wait(), 20)
        except asyncio.TimeoutError:
            p.kill()

    async def cancel(self, rid: str) -> bool:
        p = self.live.get(rid)
        if p is None:
            return False
        rec = self.records.get(rid) or {}
        self.cancelled.add(rid)
        await self._stop(p, f"aihub-ws-{rid}" if rec.get("where") == "sandbox" else None)
        return True


class SandboxMissing(Exception):
    pass


def quote(argv: list[str]) -> str:
    return " ".join(shlex.quote(a) for a in argv)
