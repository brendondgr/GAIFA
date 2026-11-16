"""GAIFA's own SearXNG (plan capability-enablement 5.2): a container `gaifa-searxng` from SearXNG's own image, pinned by
digest, on 127.0.0.1:<port> (5200 by default, the next free one up to 5209; never 8080, never host networking), with
its settings folder `data/state/searxng/managed/` mounted: a `settings.yml` GAIFA writes (the defaults, JSON results on,
the limiter off, a random secret). SearXNG's entrypoint then gives that folder to its own user (uid 977, or the matching
sub-uid under rootless podman), as with a SearXNG of yours: later changes go through the container (containers.py), and
GAIFA's own note of the port is `data/state/searxng/managed.json`. It starts and stops with the mod, and is refused while the user's own SearXNG is the
chosen one. Removing it (and, if asked, its image) is `remove`.

The container runtime is `GAIFA_CONTAINER_RUNTIME` (podman, else Docker; rootless). Commands go through `run`, which
tests replace with a fake.
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import shutil
import socket
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import source as src

NAME = "gaifa-searxng"
IMAGE = "docker.io/searxng/searxng@sha256:5ed0323b5f5f8701264ef65e239a2bd83cb57098f2b971fa30bf79c06eeae271"
FIRST_PORT, LAST_PORT = 5200, 5209

SETTINGS = """\
# GAIFA's own SearXNG (services/searxng/managed.py). Written by GAIFA; edit through the SearXNG page or the agent.
use_default_settings: true

server:
  secret_key: "{secret}"
  limiter: false
  image_proxy: false

search:
  safe_search: 0
  formats:
    - html
    - json
"""

Run = Callable[[list[str]], Awaitable[tuple[int, str]]]


async def run_cmd(argv: list[str]) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(*argv, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
                                                stderr=asyncio.subprocess.STDOUT)
    out, _ = await proc.communicate()
    return proc.returncode or 0, out.decode(errors="replace").strip()


def free(port: int) -> bool:
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


class ManagedError(Exception):
    def __init__(self, code: str, detail: str, fix: str = "") -> None:
        super().__init__(detail)
        self.code, self.detail, self.fix = code, detail, fix


class Managed:
    def __init__(self, run: Run | None = None, runtime: str | None = None, folder: Path | None = None,
                 port_free: Callable[[int], bool] = free) -> None:
        self.run = run or run_cmd
        self.runtime = runtime if runtime is not None else (os.environ.get("GAIFA_CONTAINER_RUNTIME") or
                                                            ("podman" if shutil.which("podman") else "docker" if shutil.which("docker") else ""))
        self.folder = folder or src.state_dir() / "managed"
        self.port_free = port_free

    # ---- what there is ------------------------------------------------------------------------

    @property
    def record(self) -> Path:
        """GAIFA's own note of the port, beside the mounted folder: SearXNG's entrypoint gives that folder to its own user
        (uid 977), as it does a SearXNG of yours, so GAIFA can't write there once it has run."""
        return self.folder.parent / f"{self.folder.name}.json"

    def port(self) -> int | None:
        try:
            return int(json.loads(self.record.read_text())["port"])
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def url(self) -> str | None:
        p = self.port()
        return f"http://127.0.0.1:{p}" if p else None

    async def state(self) -> dict[str, Any]:
        """{exists, running, url, runtime, image}."""
        if not self.runtime:
            return {"exists": False, "running": False, "url": None, "runtime": None, "image": IMAGE}
        rc, out = await self.run([self.runtime, "inspect", "--format", "{{.State.Status}}", NAME])
        status = out.strip().splitlines()[-1] if rc == 0 and out.strip() else ""
        return {"exists": rc == 0, "running": status == "running", "status": status or None, "url": self.url(),
                "runtime": self.runtime, "image": IMAGE}

    # ---- create, start, stop, remove ----------------------------------------------------------

    def _pick_port(self, want: int | None = None) -> int:
        for p in ([want] if want else []) + list(range(FIRST_PORT, LAST_PORT + 1)):
            if p and p != 8080 and self.port_free(p):
                return p
        raise ManagedError("no_port", f"ports {FIRST_PORT}–{LAST_PORT} are all taken",
                           "free one of them, or use your own SearXNG")

    def write_settings(self) -> Path:
        self.folder.mkdir(parents=True, exist_ok=True)
        f = self.folder / "settings.yml"
        if not f.exists():                      # kept across re-creates: the user's own changes stay
            f.write_text(SETTINGS.format(secret=secrets.token_hex(32)))
        return f

    async def create(self, port: int | None = None) -> dict[str, Any]:
        """Create and start the container; refused while the user's own SearXNG is the chosen one."""
        chosen = src.load()
        if chosen and chosen.get("source") == "yours":
            raise ManagedError("yours_chosen", "your own SearXNG is the one search uses",
                               "choose GAIFA's own first (POST /v1/source {\"source\": \"managed\"}), or keep yours")
        if not self.runtime:
            raise ManagedError("no_runtime", "neither podman nor Docker is installed",
                               "install podman (sudo dnf install podman, or sudo apt install podman), then try again")
        st = await self.state()
        if st["exists"]:
            if not st["running"]:
                await self.start()
            return await self._chosen()
        p = self._pick_port(port)
        self.write_settings()
        self.record.write_text(json.dumps({"port": p, "image": IMAGE, "runtime": self.runtime}))
        argv = [self.runtime, "run", "-d", "--name", NAME, "-p", f"127.0.0.1:{p}:8080",
                "-v", f"{self.folder}:/etc/searxng:Z", "-e", f"SEARXNG_BASE_URL=http://127.0.0.1:{p}/", IMAGE]
        rc, out = await self.run(argv)
        if rc != 0:
            raise ManagedError("create_failed", f"{self.runtime} couldn't start SearXNG: {out[-400:]}",
                               "see the error; the image comes from docker.io (network needed the first time)")
        return await self._chosen()

    async def _chosen(self) -> dict[str, Any]:
        saved = src.save("managed", self.url())
        return {**(await self.state()), "chosen": saved}

    async def start(self) -> None:
        if self.runtime:
            await self.run([self.runtime, "start", NAME])

    async def stop(self) -> None:
        if self.runtime:
            await self.run([self.runtime, "stop", "-t", "5", NAME])

    async def remove(self, image: bool = False) -> dict[str, Any]:
        """Stop and remove the container (and its image with `image`); the settings folder stays."""
        if not self.runtime:
            return {"removed": False}
        rc, out = await self.run([self.runtime, "rm", "-f", NAME])
        img = None
        if image:
            irc, iout = await self.run([self.runtime, "rmi", IMAGE])
            img = irc == 0
        chosen = src.load()
        if chosen and chosen.get("source") == "managed":
            (src.state_dir() / "source.json").unlink(missing_ok=True)
        return {"removed": rc == 0, "image_removed": img}
