"""`aihub`: the command line for the hub. Standard library only, so it starts fast
and works when the venv is broken. It talks to the running hub over HTTP and
to systemd with `systemctl --user` / `journalctl --user`.

Run through `bin/aihub`, which picks the hub's venv python.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import tomllib
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import quote

CODE = Path(__file__).resolve().parent.parent  # app.py, bin/, .venv/
ROOT = Path(os.environ.get("AIHUB_ROOT") or CODE)  # config.toml, data/
UNIT = "aihub.service"
TEMPLATE = CODE / "bin" / "aihub.service.in"
UNIT_DIR = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "systemd" / "user"
LINK = Path.home() / ".local" / "bin" / "aihub"
LATER = {"new": "2.8", "models": "3"}


class HubDown(Exception):
    pass


class ApiError(Exception):
    def __init__(self, status: int, detail: str, code: str) -> None:
        super().__init__(detail)
        self.status, self.detail, self.code = status, detail, code


# --- HTTP ---------------------------------------------------------------------


def hub_url() -> str:
    env = os.environ.get("AIHUB_URL")
    if env:
        return env.rstrip("/")
    port = 7000
    try:
        port = int(tomllib.loads((ROOT / "config.toml").read_text()).get("hub", {}).get("port", 7000))
    except (OSError, ValueError, tomllib.TOMLDecodeError):
        pass
    return f"http://127.0.0.1:{port}"


def call(method: str, path: str, body: Any = None, timeout: float = 10) -> Any:
    url = hub_url() + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"content-type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read() or b"{}")
        except ValueError:
            err = {}
        raise ApiError(e.code, err.get("detail") or e.reason, err.get("code") or "hub_error") from None
    except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
        raise HubDown(f"AIHub is not running at {hub_url()} ({getattr(e, 'reason', e)})") from None
    return json.loads(raw) if raw else None


def q(part: str) -> str:
    return quote(part, safe="")


# --- systemd ------------------------------------------------------------------


def systemctl(*args: str, quiet: bool = False) -> int:
    out = subprocess.DEVNULL if quiet else None
    return subprocess.run(["systemctl", "--user", *args], stdout=out, stderr=out).returncode


def unit_installed() -> bool:
    return (UNIT_DIR / UNIT).exists()


def render_unit(root: Path = CODE) -> str:
    return TEMPLATE.read_text().replace("@ROOT@", str(root))


def wait_up(seconds: float = 20) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            call("GET", "/api/system", timeout=2)
            return True
        except (HubDown, ApiError):
            time.sleep(0.3)
    return False


# --- formatting ---------------------------------------------------------------


def human_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n} B"


def human_secs(s: float) -> str:
    s = int(s)
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return f"{d}d {h}h" if d else f"{h}h {m}m" if h else f"{m}m {s}s" if m else f"{s}s"


def table(rows: list[list[str]]) -> str:
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    return "\n".join("  ".join(c.ljust(w) for c, w in zip(r, widths)).rstrip() for r in rows)


def down_hint() -> str:
    return "Start it with `aihub start`" + ("" if unit_installed() else " (after `aihub install`), or run `aihub serve`") + "."


# --- commands -----------------------------------------------------------------


def cmd_serve(args: argparse.Namespace) -> int:
    os.chdir(CODE)
    os.execv(sys.executable, [sys.executable, str(CODE / "app.py"), *args.rest])
    return 0  # not reached


def cmd_install(args: argparse.Namespace) -> int:
    UNIT_DIR.mkdir(parents=True, exist_ok=True)
    (UNIT_DIR / UNIT).write_text(render_unit())
    print(f"wrote {UNIT_DIR / UNIT}")
    LINK.parent.mkdir(parents=True, exist_ok=True)
    target = CODE / "bin" / "aihub"
    if LINK.is_symlink() or LINK.exists():
        if LINK.resolve() != target.resolve():
            print(f"aihub: {LINK} exists and points elsewhere; leaving it", file=sys.stderr)
    else:
        LINK.symlink_to(target)
        print(f"linked {LINK} -> {target}")
    if systemctl("daemon-reload") or systemctl("enable", UNIT, quiet=True):
        return 1
    active = systemctl("is-active", "--quiet", UNIT) == 0
    if systemctl("restart" if active else "start", UNIT):
        return 1
    print(f"{UNIT} enabled and {'restarted' if active else 'started'}")
    if not linger():
        print(f"note: lingering is off, so the hub stops when you log out. Turn it on with: loginctl enable-linger {os.environ.get('USER', '')}")
    if not wait_up():
        print(f"aihub: the hub didn't answer at {hub_url()}; see `aihub logs`", file=sys.stderr)
        return 1
    print(f"AIHub is up at {hub_url()}/")
    return 0


def cmd_uninstall(args: argparse.Namespace) -> int:
    systemctl("disable", "--now", UNIT, quiet=True)
    (UNIT_DIR / UNIT).unlink(missing_ok=True)
    systemctl("daemon-reload")
    if LINK.is_symlink() and LINK.resolve() == (CODE / "bin" / "aihub").resolve():
        LINK.unlink()
    print(f"removed {UNIT} and the aihub link; running mods were left alone (`aihub stop all` first to stop them)")
    return 0


def linger() -> bool:
    try:
        out = subprocess.run(["loginctl", "show-user", os.environ.get("USER", ""), "-p", "Linger"],
                             capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.TimeoutExpired):
        return False
    return out.strip() == "Linger=yes"


def services_or_none() -> list[dict[str, Any]] | None:
    """The mods, or None when this hub has no services API yet (before Phase 2)."""
    try:
        return call("GET", "/api/services")
    except ApiError as e:
        if e.status == 404:
            return None
        raise


def _lifecycle(action: str, target: str | None) -> int:
    if target is None:  # the hub itself
        if not unit_installed():
            print("aihub: the hub isn't installed as a service; run `aihub install` (or `aihub serve`)", file=sys.stderr)
            return 1
        rc = systemctl(action, UNIT)
        if rc == 0 and action != "stop" and not wait_up():
            print(f"aihub: the hub didn't answer at {hub_url()}; see `aihub logs`", file=sys.stderr)
            return 1
        return rc
    if target == "all":
        if action == "start" and unit_installed():
            systemctl("start", UNIT)
            wait_up()
        services = services_or_none()
        ids = [s["id"] for s in services or [] if action != "start" or s.get("enabled", True)]
        for sid in ids:
            print(f"{action} {sid}: {call('POST', f'/api/services/{q(sid)}/{action}')['state']}")
        if services is None:
            print("this hub has no mods yet (they arrive in Phase 2)")
        if action == "stop" and unit_installed():
            systemctl("stop", UNIT)
        return 0
    s = call("POST", f"/api/services/{q(target)}/{action}")
    print(f"{target}: {s['state']}")
    return 0


def cmd_start(args: argparse.Namespace) -> int:
    return _lifecycle("start", args.id)


def cmd_stop(args: argparse.Namespace) -> int:
    return _lifecycle("stop", args.id)


def cmd_restart(args: argparse.Namespace) -> int:
    return _lifecycle("restart", args.id)


def cmd_load(args: argparse.Namespace) -> int:
    s = call("POST", f"/api/services/{q(args.id)}/load")
    print(f"{args.id}: {s['load']}")
    return 0


def cmd_unload(args: argparse.Namespace) -> int:
    s = call("POST", f"/api/services/{q(args.id)}/unload")
    print(f"{args.id}: {s['load']}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    unit = "installed" if unit_installed() else "not installed"
    if unit_installed():
        state = subprocess.run(["systemctl", "--user", "is-active", UNIT], capture_output=True, text=True).stdout.strip()
        unit = f"{UNIT} {state}"
    try:
        sysinfo = call("GET", "/api/system")
    except HubDown as e:
        print(f"{e}\n{unit}\n{down_hint()}")
        return 1
    h = sysinfo["hub"]
    print(f"AIHub {h['version']} at {hub_url()}  pid {h['pid']}  up {human_secs(h['uptime_s'])}  rss {human_bytes(h['rss_bytes'])}")
    print(unit)
    d = sysinfo["disk"]
    print(f"disk {human_bytes(d['free_bytes'])} free of {human_bytes(d['total_bytes'])}   root {sysinfo['paths']['root']}")
    services = services_or_none()
    if services is None:
        print("mods: none yet (Phase 2)")
    elif services:
        rows = [["MOD", "STATE", "LOAD", "PORT", "MEMORY"]]
        for s in services:
            rows.append([s["id"], s["state"], s["load"], str(s["port"]), human_bytes(s["memory"]["used_bytes"])])
        print(table(rows))
    return 0


def cmd_logs(args: argparse.Namespace) -> int:
    unit = UNIT if args.id is None else f"aihub-{args.id}.service"
    cmd = ["journalctl", "--user", "-u", unit, "-n", str(args.n), "--no-pager", "-o", "short-iso"]
    if args.follow:
        cmd.append("-f")
    try:
        return subprocess.run(cmd).returncode
    except KeyboardInterrupt:
        return 0


def cmd_url(args: argparse.Namespace) -> int:
    print(hub_url() + "/" + (args.route or "").lstrip("/"))
    return 0


def cmd_open(args: argparse.Namespace) -> int:
    url = hub_url() + "/" + (args.route or "").lstrip("/")
    opener = shutil.which("xdg-open")
    if not opener:
        print(url)
        return 0
    return subprocess.run([opener, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode


def cmd_doctor(args: argparse.Namespace) -> int:
    """Checks that grow with the plan (full set in Phase 12.4)."""
    checks: list[tuple[str, bool, str]] = []
    venv = CODE / ".venv" / "bin" / "python"
    checks.append(("hub venv", venv.exists(), str(venv) if venv.exists() else "missing: run `uv sync`"))
    cfg_ok, cfg_note = True, "missing (defaults)"
    if (ROOT / "config.toml").exists():
        try:
            tomllib.loads((ROOT / "config.toml").read_text())
            cfg_note = "parses"
        except tomllib.TOMLDecodeError as e:
            cfg_ok, cfg_note = False, f"not valid TOML: {e}"
    checks.append(("config.toml", cfg_ok, cfg_note))
    checks.append(("systemd unit", unit_installed(), str(UNIT_DIR / UNIT) if unit_installed() else "run `aihub install`"))
    checks.append(("linger", linger(), "on" if linger() else f"loginctl enable-linger {os.environ.get('USER', '')}"))
    try:
        h = call("GET", "/api/system", timeout=3)["hub"]
        checks.append(("hub", True, f"{h['version']} pid {h['pid']} at {hub_url()}"))
    except (HubDown, ApiError) as e:
        checks.append(("hub", False, str(e)))
    for name, ok, note in checks:
        print(f"{'ok ' if ok else 'BAD'}  {name:<13} {note}")
    return 0 if all(ok for _, ok, _ in checks) else 1


def cmd_later(args: argparse.Namespace) -> int:
    print(f"aihub {args.cmd}: not built yet (plan Phase {LATER[args.cmd]})", file=sys.stderr)
    return 2


# --- entry --------------------------------------------------------------------


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="aihub", description="Control AIHub and its mods.")
    sub = ap.add_subparsers(dest="cmd", required=True, metavar="command")

    p = sub.add_parser("serve", help="run the hub in the foreground (python app.py)")
    p.add_argument("rest", nargs=argparse.REMAINDER, help="passed to app.py (--port, --dev, ...)")
    p.set_defaults(fn=cmd_serve)
    sub.add_parser("install", help="install and start the aihub systemd user service").set_defaults(fn=cmd_install)
    sub.add_parser("uninstall", help="stop and remove the aihub service").set_defaults(fn=cmd_uninstall)
    for name, fn, what in (("start", cmd_start, "start"), ("stop", cmd_stop, "stop"), ("restart", cmd_restart, "restart")):
        p = sub.add_parser(name, help=f"{what} the hub (no id), a mod, or everything (all)")
        p.add_argument("id", nargs="?")
        p.set_defaults(fn=fn)
    sub.add_parser("status", help="hub and mod status").set_defaults(fn=cmd_status)
    p = sub.add_parser("logs", help="journal of the hub (no id) or a mod")
    p.add_argument("id", nargs="?")
    p.add_argument("-f", "--follow", action="store_true")
    p.add_argument("-n", type=int, default=100, metavar="N", help="lines (default 100)")
    p.set_defaults(fn=cmd_logs)
    for name, fn in (("load", cmd_load), ("unload", cmd_unload)):
        p = sub.add_parser(name, help=f"{name} a mod's models")
        p.add_argument("id")
        p.set_defaults(fn=fn)
    for name, fn, what in (("open", cmd_open, "open the UI in a browser"), ("url", cmd_url, "print the UI's URL")):
        p = sub.add_parser(name, help=what)
        p.add_argument("route", nargs="?")
        p.set_defaults(fn=fn)
    sub.add_parser("doctor", help="check the install").set_defaults(fn=cmd_doctor)
    p = sub.add_parser("new", help=f"create a mod from the template (Phase {LATER['new']})")
    p.add_argument("id")
    p.set_defaults(fn=cmd_later)
    p = sub.add_parser("models", help=f"scan | list | verify <id> (Phase {LATER['models']})")
    p.add_argument("action", choices=["scan", "list", "verify"])
    p.add_argument("id", nargs="?")
    p.set_defaults(fn=cmd_later)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        return args.fn(args)
    except HubDown as e:
        print(f"aihub: {e}\n{down_hint()}", file=sys.stderr)
        return 1
    except ApiError as e:
        print(f"aihub: {e.detail} ({e.code})", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
