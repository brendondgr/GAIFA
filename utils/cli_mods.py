"""`aihub new | install <id> | rescan`: making and installing mods. Standard library only, like cli.py.

`aihub new <id>` copies `services/_template/`, fills in the id, name and a free port,
runs its `install.sh`, and asks a running hub to pick it up (`POST /api/services/rescan`).
"""

from __future__ import annotations

import argparse
import re
import shutil
import socket
import subprocess
import sys
import time
import tomllib
from pathlib import Path
from typing import Any

# cli.py hands itself over (see cli._mods): run as a script, `utils` isn't an importable package.
cli: Any = None

ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,31}$")
TEMPLATE_ID = "_template"
TOKENS = ("__ID__", "__NAME__", "__PORT__")
TEXT_SUFFIXES = {".toml", ".py", ".md", ".js", ".sh", ".txt", ".html", ".json", ".css", ".cfg", ".ini", ".yaml", ".yml"}
IGNORE = shutil.ignore_patterns(".venv", "__pycache__", "*.pyc", "runtime", ".env", "node_modules")
DEFAULT_RANGE = (5100, 5199)


def services_dir() -> Path:
    return cli.ROOT / "services"


def template_dir() -> Path:
    # The template ships with the code; new mods go under the data root (they're the same folder normally).
    return cli.CODE / "services" / TEMPLATE_ID


def _config() -> dict[str, Any]:
    try:
        return tomllib.loads((cli.ROOT / "config.toml").read_text())
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def used_ports() -> dict[int, str]:
    """Ports taken by the hub, every mod's manifest and config.toml overrides: {port: who}."""
    cfg = _config()
    used: dict[int, str] = {int(cfg.get("hub", {}).get("port", 7000)): "the hub"}
    base = services_dir()
    if base.is_dir():
        for manifest in sorted(base.glob("*/service.toml")):
            try:
                port = tomllib.loads(manifest.read_text()).get("run", {}).get("port")
            except (OSError, tomllib.TOMLDecodeError):
                continue
            if isinstance(port, int):
                used.setdefault(port, manifest.parent.name)
    for sid, table in (cfg.get("services") or {}).items():
        if isinstance(table, dict) and isinstance(table.get("port"), int):
            used.setdefault(table["port"], sid)
    return used


def listening(port: int) -> bool:
    for family, host in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
        try:
            with socket.socket(family, socket.SOCK_STREAM) as s:
                s.settimeout(0.3)
                if s.connect_ex((host, port)) == 0:
                    return True
        except OSError:
            continue
    return False


def pick_port() -> int | None:
    lo, hi = DEFAULT_RANGE
    rng = _config().get("ports", {}).get("new_mods")
    if isinstance(rng, list) and len(rng) == 2 and all(isinstance(x, int) for x in rng):
        lo, hi = rng
    used = used_ports()
    for port in range(lo, hi + 1):
        if port not in used and not listening(port):
            return port
    return None


def default_name(sid: str) -> str:
    return " ".join(w.capitalize() for w in sid.split("-") if w)


def fill(folder: Path, values: dict[str, str]) -> None:
    for path in folder.rglob("*"):
        if path.is_file() and path.suffix in TEXT_SUFFIXES:
            text = path.read_text()
            new = text
            for token, value in values.items():
                new = new.replace(token, value)
            if new != text:
                path.write_text(new)


def cmd_new(args: argparse.Namespace) -> int:
    sid: str = args.id
    if not ID_RE.match(sid):
        return _fail(f"{sid!r} isn't a valid mod id: use 2–32 lowercase letters, digits and -, starting with a letter")
    dest = services_dir() / sid
    if dest.exists():
        return _fail(f"services/{sid} already exists")
    template = template_dir()
    if not (template / "service.toml").is_file():
        return _fail(f"the template is missing ({template})")
    name = args.name or default_name(sid)
    if any(c in name for c in '"\\`\n\r') or not name.strip() or len(name) > 64:
        return _fail("--name must be 1–64 characters, without quotes, backslashes or backticks")
    if args.port is not None:
        port = args.port
        if not 1 <= port <= 65535:
            return _fail(f"--port {port} is not a port (1–65535)")
        who = used_ports().get(port)
        if who:
            return _fail(f"port {port} is already used by {who}")
        if listening(port):
            return _fail(f"port {port} is in use by another program")
    else:
        found = pick_port()
        if found is None:
            return _fail("no free port in config.toml [ports] new_mods; pass --port")
        port = found

    services_dir().mkdir(parents=True, exist_ok=True)
    shutil.copytree(template, dest, ignore=IGNORE)
    fill(dest, {"__ID__": sid, "__NAME__": name, "__PORT__": str(port)})
    print(f"created services/{sid} ({name}, port {port})")

    if not args.no_install:
        rc = run_install(dest)
        if rc != 0:
            print(f"aihub: install.sh failed; fix it, run services/{sid}/install.sh, then `aihub rescan`", file=sys.stderr)
            return 1

    state = _pick_up(sid)
    print()
    print("Next:")
    print(f"  edit      services/{sid}/server.py and service.toml   (guide: docs/mods.md)")
    print(f"  check     aihub check {sid}")
    print(f"  reload    aihub restart {sid}   (after editing; `aihub rescan` after adding or removing mods)")
    print(f"  open      {cli.hub_url()}/#/s/{sid}")
    print(f"  call      {cli.hub_url()}/api/s/{sid}/v1/hello?name=you")
    return 0 if state in (None, "ready", "stopped") else 1


def _pick_up(sid: str) -> str | None:
    """Ask a running hub to load the new mod and wait until it settles. None when the hub is down."""
    try:
        cli.call("POST", "/api/services/rescan")
    except cli.HubDown:
        print("AIHub isn't running; `aihub start` will load the new mod.")
        return None
    except cli.ApiError as e:
        print(f"aihub: the hub couldn't rescan: {e.detail} ({e.code}); run `aihub restart`", file=sys.stderr)
        return None
    deadline = time.monotonic() + 90
    s: dict[str, Any] = {}
    while time.monotonic() < deadline:
        try:
            s = cli.call("GET", f"/api/services/{cli.q(sid)}")
        except cli.ApiError:
            time.sleep(0.3)
            continue
        if s["state"] not in ("starting", "stopping") and not (s["state"] == "stopped" and s.get("autostart") and s.get("enabled")):
            break
        time.sleep(0.3)
    state = s.get("state")
    print(f"AIHub picked it up: {sid} is {state}")
    if state == "failed":
        print("  " + str(s.get("last_error") or s.get("manifest_errors")).replace("\n", "\n  "), file=sys.stderr)
    return state


def run_install(folder: Path) -> int:
    """Run the mod's `[run] install` script (default install.sh) in its folder."""
    script = "install.sh"
    try:
        script = tomllib.loads((folder / "service.toml").read_text()).get("run", {}).get("install") or script
    except (OSError, tomllib.TOMLDecodeError):
        pass
    path = folder / script
    if not path.is_file():
        print(f"no {script} in services/{folder.name}; nothing to install")
        return 0
    print(f"running services/{folder.name}/{script} …")
    return subprocess.run(["bash", str(path)], cwd=folder).returncode


def cmd_install_mod(sid: str) -> int:
    folder = services_dir() / sid
    if not (folder / "service.toml").is_file():
        return _fail(f"no mod folder services/{sid}")
    return run_install(folder)


def cmd_rescan(args: argparse.Namespace) -> int:
    r = cli.call("POST", "/api/services/rescan")
    for key in ("added", "removed", "changed"):
        if r[key]:
            print(f"{key}: {', '.join(r[key])}")
    if not any(r.values()):
        print("no changes")
    return 0


def _fail(msg: str) -> int:
    print(f"aihub: {msg}", file=sys.stderr)
    return 2
