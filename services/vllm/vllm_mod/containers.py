"""Where the engine runs: a podman container, or (VLLM_FAKE=1) the fake engine as a plain process.

Both keep the same contract, so the engine code above them is identical: `run` starts it detached,
`state` says running / exited / missing, `logs` follows its output from the start, `stop` and
`remove` end it, `list` finds ours (for adoption after an adapter restart)."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import signal
import sys
import time
from collections.abc import AsyncIterator
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from .profiles import LABEL, NAME_PREFIX


class ContainerError(Exception):
    pass


@dataclass
class Found:
    name: str
    profile: str | None
    running: bool


async def _exec(*args: str, timeout: float = 60) -> tuple[int, str, str]:
    p = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        out, err = await asyncio.wait_for(p.communicate(), timeout)
    except TimeoutError:
        p.kill()
        raise ContainerError(f"{args[0]} {args[1]} timed out after {timeout:.0f}s") from None
    return p.returncode or 0, out.decode(errors="replace"), err.decode(errors="replace")


async def _lines(stream: asyncio.StreamReader) -> AsyncIterator[str]:
    """Lines split on \\n and \\r (vLLM's progress bars redraw with \\r)."""
    buf = b""
    while True:
        chunk = await stream.read(65536)
        if not chunk:
            break
        buf += chunk
        *parts, buf = buf.replace(b"\r", b"\n").split(b"\n")
        for part in parts:
            if part.strip():
                yield part.decode(errors="replace")
    if buf.strip():
        yield buf.decode(errors="replace")


class Podman:
    """`scope`: start podman in its own transient systemd scope. Otherwise conmon (podman's monitor,
    which holds the container's output pipe) stays in the adapter's unit: systemd would kill it with
    the adapter, and the engine's output would land twice in the mod's log (journald, and our copy)."""

    def __init__(self, podman: str = "podman", scope: bool = True):
        self.podman = podman
        self.scope = scope and shutil.which("systemd-run") is not None

    async def run(self, cmd: list[str]) -> None:
        if self.scope:
            name = cmd[cmd.index("--name") + 1]
            cmd = ["systemd-run", "--user", "--scope", "--quiet", "--collect",
                   f"--unit={name}-{int(time.time())}", *cmd]
        code, _, err = await _exec(*cmd, timeout=120)
        if code:
            raise ContainerError(err.strip().splitlines()[-1] if err.strip() else f"podman run exited {code}")

    async def state(self, name: str) -> str:
        code, out, _ = await _exec(self.podman, "inspect", "--format", "{{.State.Status}}", name)
        if code:
            return "missing"
        return "running" if out.strip() in ("running", "created", "configured") else "exited"

    async def stop(self, name: str, timeout: int = 30) -> None:
        await _exec(self.podman, "stop", "-t", str(timeout), name, timeout=timeout + 30)

    async def remove(self, name: str) -> None:
        await _exec(self.podman, "rm", "-f", name, timeout=60)

    async def list(self) -> list[Found]:
        code, out, _ = await _exec(self.podman, "ps", "-a", "--filter", f"label={LABEL}", "--format", "json")
        if code:
            return []
        found = []
        for c in json.loads(out or "[]"):
            names = c.get("Names") or []
            name = names[0] if names else ""
            if name.startswith(NAME_PREFIX):
                found.append(Found(name, (c.get("Labels") or {}).get("aihub.profile"), c.get("State") == "running"))
        return found

    async def logs(self, name: str, tail: int | None = None) -> AsyncIterator[str]:
        extra = ["--tail", str(tail)] if tail else []
        p = await asyncio.create_subprocess_exec(self.podman, "logs", "-f", *extra, name, stdout=asyncio.subprocess.PIPE,
                                                 stderr=asyncio.subprocess.STDOUT)
        try:
            assert p.stdout is not None
            async for line in _lines(p.stdout):
                yield line
        finally:
            if p.returncode is None:
                p.kill()
                await p.wait()


class FakeContainers:
    """The fake engine as a detached process; its pid and log live in the state folder, so a new
    adapter can adopt it like a container."""

    def __init__(self, state_dir: Path):
        self.dir = state_dir / "fake"

    def _rec(self, name: str) -> Path:
        return self.dir / f"{name}.json"

    def _log(self, name: str) -> Path:
        return self.dir / f"{name}.log"

    def _read(self, name: str) -> dict | None:
        try:
            return json.loads(self._rec(name).read_text())
        except (OSError, ValueError):
            return None

    async def run(self, cmd: list[str]) -> None:
        name = cmd[cmd.index("--name") + 1]
        if self._read(name):
            raise ContainerError(f"the container name {name!r} is already in use")
        labels = [cmd[i + 1] for i, x in enumerate(cmd) if x == "--label"]
        env = dict(os.environ)
        env.update(cmd[i + 1].split("=", 1) for i, x in enumerate(cmd) if x == "-e")  # type: ignore[arg-type]
        serve = cmd[cmd.index("vllm"):]
        self.dir.mkdir(parents=True, exist_ok=True)
        log = open(self._log(name), "wb")
        p = await asyncio.create_subprocess_exec(sys.executable, "-m", "vllm_mod.fake_engine", *serve[1:],
                                                 stdout=log, stderr=asyncio.subprocess.STDOUT, env=env,
                                                 start_new_session=True,
                                                 cwd=str(Path(__file__).resolve().parent.parent))
        log.close()
        profile = next((lb.split("=", 1)[1] for lb in labels if lb.startswith("aihub.profile=")), None)
        self._rec(name).write_text(json.dumps({"pid": p.pid, "profile": profile, "started": time.time()}))
        self._procs = getattr(self, "_procs", {})
        self._procs[name] = p        # keeps the child reaped while this adapter lives

    def _alive(self, pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        try:   # a zombie (exited, not reaped by its parent) counts as exited
            return Path(f"/proc/{pid}/stat").read_text().split(")")[1].split()[0] != "Z"
        except (OSError, IndexError):
            return True

    async def state(self, name: str) -> str:
        rec = self._read(name)
        if not rec:
            return "missing"
        return "running" if self._alive(rec["pid"]) else "exited"

    async def stop(self, name: str, timeout: int = 30) -> None:
        rec = self._read(name)
        if not rec or not self._alive(rec["pid"]):
            return
        os.kill(rec["pid"], signal.SIGTERM)
        deadline = time.monotonic() + timeout
        while self._alive(rec["pid"]) and time.monotonic() < deadline:
            await asyncio.sleep(0.05)
        if self._alive(rec["pid"]):
            os.kill(rec["pid"], signal.SIGKILL)

    async def remove(self, name: str) -> None:
        await self.stop(name, timeout=2)
        self._rec(name).unlink(missing_ok=True)
        self._log(name).unlink(missing_ok=True)

    async def list(self) -> list[Found]:
        out = []
        for f in sorted(self.dir.glob("*.json")) if self.dir.is_dir() else []:
            rec = self._read(f.stem)
            if rec:
                out.append(Found(f.stem, rec.get("profile"), self._alive(rec["pid"])))
        return out

    async def logs(self, name: str, tail: int | None = None) -> AsyncIterator[str]:
        """Follow the log file from the start (or about the last `tail` lines) until the process exits."""
        path, pos, buf = self._log(name), 0, ""
        if tail:
            with suppress(OSError):
                pos = max(0, path.stat().st_size - 120 * tail)
        while True:
            alive = await self.state(name) == "running"
            try:
                with open(path, "rb") as f:
                    f.seek(pos)
                    data = f.read()
                    pos += len(data)
            except OSError:
                data = b""
            buf += data.decode(errors="replace").replace("\r", "\n")
            *parts, buf = buf.split("\n")
            for part in parts:
                if part.strip():
                    yield part
            if not alive and not data:
                if buf.strip():
                    yield buf
                return
            await asyncio.sleep(0.05)
