"""The SearXNG container (plan 26.3): find it with Docker or podman, and the only writes this mod
makes outside the project: `settings.yml` and its backups `settings.yml.aihub-<date>`, in the folder
bind-mounted at the container's settings path.

The file belongs to the container's `searxng` user (uid 977 in the image) and isn't writable from
the host, so writes go through the container (`docker exec`, which the `docker` group allows). A
write never leaves the file half written: the new text goes to `.settings.yml.aihub-new` next to it
(a `cp -p` of the file, so owner and mode stay), its size is checked, and `mv -f` renames it over
`settings.yml` in one step. Only when the rename is refused (settings.yml bind-mounted on its own)
is the checked copy written over the file in place. Restoring a backup goes the same way. Only the
newest `KEEP_BACKUPS` backups are kept; older ones, matched by their exact name, are deleted.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import re
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

BACKUP_RE = re.compile(r"^settings\.yml\.aihub-(\d{4}-\d{2}-\d{2}T\d{6})(?:-(\d+))?$")
DEFAULT_SETTINGS_IN = "/etc/searxng/settings.yml"
KEEP_BACKUPS = 10

# $0 settings.yml, $1 "-" (the new text on stdin, $2 bytes) or a backup to copy back. The new file is
# a copy of the old one (owner, mode) with the new text, checked for size, then renamed over it.
_REPLACE = r'''
f="$0"; t="${f%/*}/.${f##*/}.aihub-new"
rm -f "$t" && cp -p "$f" "$t" || exit 1
if [ "$1" = - ]; then n="$2"; cat > "$t" || { rm -f "$t"; exit 1; }
else n=$(($(wc -c < "$1"))) && cat "$1" > "$t" || { rm -f "$t"; exit 1; }; fi
got=$(($(wc -c < "$t")))
if [ "$got" -ne "$n" ]; then rm -f "$t"; echo "the new settings.yml came out $got bytes of $n; settings.yml is unchanged" >&2; exit 1; fi
mv -f "$t" "$f" 2>/dev/null && exit 0
cat "$t" > "$f"; s=$?; rm -f "$t"; exit $s
'''


class RuntimeError_(Exception):
    """A container command failed; `detail` has its output."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


@dataclass
class Container:
    runtime: str                      # docker | podman
    id: str
    name: str
    image: str
    state: str                        # running, exited, …
    settings_in: str = DEFAULT_SETTINGS_IN          # the path inside the container
    settings_host: str | None = None                # the bind-mounted file on the host
    compose_dir: str | None = None
    compose_service: str | None = None
    url: str | None = None            # from its network mode, ports and env
    env: dict[str, str] = field(default_factory=dict)

    def public(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if k != "env"}


def backup_order(name: str) -> tuple[str, int]:
    """Oldest first: by the date in the name, then its -2, -3 … (so -10 comes after -9)."""
    m = BACKUP_RE.match(name)
    return (m.group(1), int(m.group(2) or 1)) if m else ("", 0)


def backup_name(now: datetime | None = None) -> str:
    return f"settings.yml.aihub-{(now or datetime.now()).strftime('%Y-%m-%dT%H%M%S')}"


class Runtime(Protocol):
    async def find(self) -> Container | None: ...
    async def read(self, c: Container) -> str: ...
    async def backup(self, c: Container) -> str: ...
    async def write(self, c: Container, text: str) -> None: ...
    async def restore(self, c: Container, backup: str) -> None: ...
    def backups(self, c: Container) -> list[str]: ...
    async def prune(self, c: Container, keep: int) -> list[str]: ...
    async def restart(self, c: Container) -> None: ...


def _url_from_inspect(info: dict[str, Any], env: dict[str, str]) -> str | None:
    host_cfg = info.get("HostConfig") or {}
    if host_cfg.get("NetworkMode") == "host":
        bind = env.get("BIND_ADDRESS") or ""
        port = (bind.rsplit(":", 1)[1] if ":" in bind else "") or env.get("GRANIAN_PORT") or env.get("SEARXNG_PORT") or "8080"
        return f"http://127.0.0.1:{port}"
    ports = ((info.get("NetworkSettings") or {}).get("Ports") or {}).get("8080/tcp") or []
    for p in ports:
        if p.get("HostPort"):
            ip = p.get("HostIp") or "127.0.0.1"
            ip = "127.0.0.1" if ip in ("0.0.0.0", "::", "") else ip
            return f"http://{ip}:{p['HostPort']}"
    return None


def container_from_inspect(runtime: str, info: dict[str, Any]) -> Container:
    cfg = info.get("Config") or {}
    env = dict(e.split("=", 1) for e in cfg.get("Env") or [] if "=" in e)
    labels = cfg.get("Labels") or {}
    settings_in = env.get("SEARXNG_SETTINGS_PATH") or env.get("__SEARXNG_SETTINGS_PATH") or DEFAULT_SETTINGS_IN
    host = None
    for m in info.get("Mounts") or []:
        dest, src = m.get("Destination") or "", m.get("Source") or ""
        if dest == settings_in:
            host = src
        elif m.get("Type") == "bind" and dest == str(PurePosixPath(settings_in).parent):
            host = str(Path(src) / PurePosixPath(settings_in).name)
    state = (info.get("State") or {}).get("Status") or "unknown"
    return Container(runtime, info.get("Id", "")[:12], (info.get("Name") or "").lstrip("/"), cfg.get("Image", ""), state,
                     settings_in, host, labels.get("com.docker.compose.project.working_dir"),
                     labels.get("com.docker.compose.service"), _url_from_inspect(info, env), env)


class CliRuntime:
    """Docker or podman through its command line. `binary` is found on PATH unless given."""

    def __init__(self, binary: str | None = None) -> None:
        self.binary = binary

    def _bin(self) -> str | None:
        if self.binary:
            return self.binary
        return next((b for b in ("docker", "podman") if shutil.which(b)), None)

    async def _run(self, *args: str, stdin: bytes | None = None, cwd: str | None = None, timeout: float = 60) -> str:
        b = self._bin()
        if b is None:
            raise RuntimeError_("neither docker nor podman is installed")
        try:
            p = await asyncio.create_subprocess_exec(b, *args, stdin=asyncio.subprocess.PIPE if stdin is not None else None,
                                                     stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, cwd=cwd)
        except OSError as e:
            raise RuntimeError_(f"can't run {b}: {e.strerror}") from None
        try:
            out, err = await asyncio.wait_for(p.communicate(stdin), timeout)
        except BaseException as e:   # a timeout, or the watch loop cancelled at shutdown: never leave the child running
            if p.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    p.kill()
                with contextlib.suppress(BaseException):
                    await asyncio.wait_for(p.wait(), 5)   # reaped, so nothing holds the process at exit
            if isinstance(e, TimeoutError):
                raise RuntimeError_(f"{Path(b).name} {' '.join(args[:2])} took longer than {timeout:.0f} s") from None
            raise
        if p.returncode != 0:
            raise RuntimeError_(f"{Path(b).name} {' '.join(args[:3])}: {(err or out).decode(errors='replace').strip()[:400]}")
        return out.decode(errors="replace")

    async def find(self) -> Container | None:
        try:
            listing = await self._run("ps", "-a", "--format", "{{json .}}", timeout=15)
        except RuntimeError_:
            return None
        rows = []
        for line in listing.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
        hits = [r for r in rows if re.search(r"(^|/)searxng/", str(r.get("Image", "")))]
        hits.sort(key=lambda r: 0 if str(r.get("State", "")).lower() == "running" else 1)
        if not hits:
            return None
        try:   # the container can go between `ps` and `inspect`: then nothing is found, this round
            info = json.loads(await self._run("inspect", str(hits[0].get("ID") or hits[0].get("Id")), timeout=15))[0]
            name = Path(self._bin() or "docker").name
            return container_from_inspect("podman" if "podman" in name else "docker", info)
        except (RuntimeError_, ValueError, LookupError, TypeError, AttributeError):
            return None

    async def read(self, c: Container) -> str:
        if c.settings_host and Path(c.settings_host).is_file():
            return Path(c.settings_host).read_text()
        return await self._run("exec", c.id, "cat", c.settings_in)

    def _backup_path(self, c: Container, name: str) -> str:
        if not BACKUP_RE.match(name):
            raise RuntimeError_(f"{name!r} isn't a settings backup")
        return str(PurePosixPath(c.settings_in).with_name(name))

    async def backup(self, c: Container) -> str:
        name = backup_name()
        taken = set(self.backups(c))
        base, n = name, 2
        while name in taken:
            name, n = f"{base}-{n}", n + 1
        await self._run("exec", c.id, "cp", "-p", c.settings_in, self._backup_path(c, name))
        return name

    async def write(self, c: Container, text: str) -> None:
        data = text.encode()
        await self._run("exec", "-i", c.id, "sh", "-c", _REPLACE, c.settings_in, "-", str(len(data)), stdin=data)

    async def restore(self, c: Container, backup: str) -> None:
        await self._run("exec", c.id, "sh", "-c", _REPLACE, c.settings_in, self._backup_path(c, backup))

    def backups(self, c: Container) -> list[str]:
        """This mod's backups, newest first."""
        if not c.settings_host:
            return []
        folder = Path(c.settings_host).parent
        try:
            return sorted((p.name for p in folder.iterdir() if BACKUP_RE.match(p.name)), key=backup_order, reverse=True)
        except OSError:
            return []

    async def prune(self, c: Container, keep: int = KEEP_BACKUPS) -> list[str]:
        """Delete this mod's backups past the newest `keep`; returns their names."""
        old = self.backups(c)[max(keep, 1):]
        if old:
            await self._run("exec", c.id, "rm", "-f", "--", *(self._backup_path(c, n) for n in old))
        return old

    async def restart(self, c: Container) -> None:
        if c.compose_dir and c.compose_service and Path(c.compose_dir).is_dir():
            await self._run("compose", "restart", c.compose_service, cwd=c.compose_dir, timeout=120)
        else:
            await self._run("restart", c.id, timeout=120)
