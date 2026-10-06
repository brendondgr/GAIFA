"""``lcpp service …`` — install and control lcppd as a systemd user unit, or, inside AIHub
(services/lcpp), hand start/stop/restart/status/logs to `aihub`.

The user manager starts it at boot (linger is enabled for this user), so the
daemon is up before anyone logs in, idle, with no model loaded.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from lcpp.paths import Paths

UNIT = "lcpp.service"


def unit_dir() -> Path:
    return Path.home() / ".config/systemd/user"


def systemctl(*args: str, check: bool = False) -> int:
    return subprocess.run(["systemctl", "--user", *args], check=check).returncode


def install(paths: Paths) -> int:
    template = paths.root / "deploy/systemd" / UNIT
    python = paths.root / ".venv/bin/python"
    if not python.exists():
        print(f"{python} is missing; run `uv sync` in {paths.root} first", file=sys.stderr)
        return 1
    target = unit_dir() / UNIT
    target.parent.mkdir(parents=True, exist_ok=True)
    rendered = template.read_text().replace("@REPO_ROOT@", str(paths.root))
    changed = not target.exists() or target.read_text() != rendered
    target.write_text(rendered)
    systemctl("daemon-reload", check=True)
    systemctl("enable", UNIT, check=True)
    if changed:
        systemctl("restart", UNIT, check=True)
    else:
        systemctl("start", UNIT, check=True)
    linger = subprocess.run(["loginctl", "show-user", str(Path.home().owner()), "-p", "Linger", "--value"],
                            capture_output=True, text=True).stdout.strip()
    print(f"installed {target} ({'updated' if changed else 'unchanged'}); enabled and running")
    if linger != "yes":
        print("note: linger is off, so lcppd starts at login rather than at boot "
              "(enable with: loginctl enable-linger)")
    return 0


def uninstall() -> int:
    systemctl("disable", "--now", UNIT)
    (unit_dir() / UNIT).unlink(missing_ok=True)
    systemctl("daemon-reload")
    print("lcpp.service removed (running instances, if any, keep running)")
    return 0


def aihub(paths: Paths) -> Path | None:
    """AIHub's `aihub` command when lcpp runs as its mod (services/lcpp), else None."""
    cli = paths.root.parent.parent / "bin" / "aihub"
    return cli if (paths.root / "service.toml").is_file() and cli.is_file() else None


def run(cmd: str) -> int:
    paths = Paths.default()
    hub = aihub(paths)
    if hub:  # AIHub runs lcppd as its `lcpp` mod; lcpp.service is not used
        if cmd in ("install", "uninstall"):
            print("lcppd runs as AIHub's lcpp mod; AIHub starts it (see `aihub status`)")
            return 0
        args = {"logs": ["logs", "-f", "lcpp"], "status": ["status"]}.get(cmd, [cmd, "lcpp"])
        return subprocess.run([str(hub), *args]).returncode
    if cmd == "install":
        return install(paths)
    if cmd == "uninstall":
        return uninstall()
    if cmd in ("start", "stop", "restart"):
        return systemctl(cmd, UNIT)
    if cmd == "status":
        return systemctl("status", UNIT, "--no-pager")
    if cmd == "logs":
        return subprocess.run(["journalctl", "--user", "-u", UNIT, "-f", "-n", "50"]).returncode
    raise ValueError(cmd)
