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
WAIT_S = 600  # start/stop/restart wait for the mod to settle (start_timeout_s can be minutes)


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
    """Decimal units, like the UI: 1 GB = 10⁹ bytes."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1000 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1000
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


def _mods() -> Any:
    """utils/cli_mods.py (new, install <id>, rescan), loaded only when one of them runs."""
    try:
        from utils import cli_mods  # imported as a package (tests)
    except ImportError:
        import cli_mods  # type: ignore[no-redef]  # run as a script: utils/ is on sys.path
    cli_mods.cli = sys.modules[__name__]
    return cli_mods


def cmd_models(args: argparse.Namespace) -> int:
    """utils/cli_models.py, loaded only when a models command runs."""
    try:
        from utils import cli_models
    except ImportError:
        import cli_models  # type: ignore[no-redef]
    cli_models.cli = sys.modules[__name__]
    return cli_models.cmd_models(args)


def cmd_docs(args: argparse.Namespace) -> int:
    """utils/setupdocs/ (plan 23): the mods index in docs/setup/README.md and this machine's model
    inventory in data/state/setup/models/ (local). Needs no hub."""
    try:
        from utils import setupdocs
    except ImportError:
        import setupdocs  # type: ignore[no-redef]
    report = setupdocs.sync(ROOT, check=args.check)
    for rel in report.written:
        print(f"{'would write' if args.check else 'wrote'} {rel}")
    for rel in report.removed:
        print(f"removed {rel} (its model is gone and it had no hand-written text)")
    problems = report.problems(strict=args.strict)
    for p in problems:
        print(f"aihub docs: {p}", file=sys.stderr)
    if not args.strict and report.uncovered_mods:
        print(f"{len(report.uncovered_mods)} mod(s) without a setup doc: {', '.join(report.uncovered_mods)} (--strict fails on them)")
    if not args.check and (report.uncovered or report.unsourced):
        print(f"inventory notes: {len(report.uncovered)} model(s) no setup doc runs, {len(report.unsourced)} without a recorded source (data/state/setup/models/README.md)")
    if not problems and not report.written and not report.removed:
        print("setup docs are up to date")
    return 1 if problems else 0


def _setup() -> Any:
    """utils/cli_setup.py (plan 23.9). Its arguments are part of `aihub --help`, so it's loaded the
    way this file was: as a script (utils/ on sys.path, no `utils` package) or as the package (tests)."""
    if __package__:
        from utils import cli_setup
    else:
        here = str(Path(__file__).resolve().parent)
        if here not in sys.path:
            sys.path.insert(0, here)   # utils/ itself, as when bin/aihub runs this file: never the utils package
        import cli_setup  # type: ignore[no-redef]
    cli_setup.cli = sys.modules[__name__]
    return cli_setup


def cmd_setup(args: argparse.Namespace) -> int:
    return _setup().cmd_setup(args)


def cmd_backup(args: argparse.Namespace) -> int:
    """utils/cli_backup.py (plan 12.5), loaded only when a backup runs."""
    try:
        from utils import cli_backup
    except ImportError:
        import cli_backup  # type: ignore[no-redef]
    return cli_backup.cmd_backup(args, Path(os.environ.get("AIHUB_ROOT") or CODE))  # read now, not at import


def cmd_new(args: argparse.Namespace) -> int:
    return _mods().cmd_new(args)


def cmd_rescan(args: argparse.Namespace) -> int:
    return _mods().cmd_rescan(args)


def cmd_check(args: argparse.Namespace) -> int:
    return _mods().cmd_check(args)


def cmd_install(args: argparse.Namespace) -> int:
    if args.id:
        return _mods().cmd_install_mod(args.id)
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
        services = services_or_none() or []
        rc = 0
        for s in services:
            if s["kind"] == "external" or s["manifest_errors"] or (action == "start" and not s.get("enabled", True)):
                continue
            if action == "stop" and s["state"] == "stopped":
                continue
            try:
                rc |= _report(s["id"], call("POST", f"/api/services/{q(s['id'])}/{action}?wait=1", timeout=WAIT_S))
            except ApiError as e:
                print(f"{s['id']}: {e.detail} ({e.code})", file=sys.stderr)
                rc = 1
        if action == "stop" and unit_installed():
            systemctl("stop", UNIT)
        return rc
    return _report(target, call("POST", f"/api/services/{q(target)}/{action}?wait=1", timeout=WAIT_S))


def _report(sid: str, s: dict[str, Any]) -> int:
    """Print a mod's state after start/stop/restart; 1 when it ended up failed."""
    print(f"{sid}: {s['state']}")
    if s["state"] == "failed" and s.get("last_error"):
        print("  " + s["last_error"].replace("\n", "\n  "), file=sys.stderr)
        return 1
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
    if not services:
        print("mods: none (add one with `aihub new <id>`)")
    else:
        rows = [["MOD", "STATE", "LOAD", "PORT", "MEMORY"]]
        for s in services:
            rows.append([s["id"], s["state"], s["load"], str(s["port"]), human_bytes(s["memory"]["used_bytes"])])
        print(table(rows))
        for s in services:
            for err in s["manifest_errors"]:
                print(f"  {s['id']}: {err}", file=sys.stderr)
    return 0


def cmd_logs(args: argparse.Namespace) -> int:
    """`data/logs/<id>.log` (or `aihub.log`) when it exists (plan 16.1), else the journal."""
    root = Path(os.environ.get("AIHUB_ROOT") or CODE)
    f = root / "data" / "logs" / f"{args.id or 'aihub'}.log"
    if f.is_file() and not getattr(args, "journal", False):
        cmd = ["tail", "-n", str(args.n)] + (["-F"] if args.follow else []) + [str(f)]
        try:
            return subprocess.run(cmd).returncode
        except KeyboardInterrupt:
            return 0
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


DOCTOR_MARK = {"ok": "ok ", "note": "·  ", "warn": "!  ", "fail": "BAD"}


def cmd_doctor(args: argparse.Namespace) -> int:
    """This install's checks (venv, config, unit), then the hub's own (`GET /api/doctor`, plan 12.4):
    models on disk, manifests, paths outside the project, ports, units, disk, offline mods."""
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
    if getattr(args, "inventory", False):
        return cmd_inventory(args)
    report = None
    try:
        h = call("GET", "/api/system", timeout=3)["hub"]
        checks.append(("hub", True, f"{h['version']} pid {h['pid']} at {hub_url()}"))
        report = call("GET", "/api/doctor", timeout=60)
    except (HubDown, ApiError) as e:
        checks.append(("hub", False, str(e)))
    if args.json:
        print(json.dumps({"local": [{"name": n, "ok": ok, "detail": d} for n, ok, d in checks], "hub": report}, indent=1))
    else:
        for name, ok, note in checks:
            print(f"{'ok ' if ok else 'BAD'}  {name:<13} {note}")
        for c in (report or {}).get("checks", []):
            if c["level"] == "ok" and not args.verbose:
                continue
            print(f"{DOCTOR_MARK[c['level']]}  {c['area']:<13} {c['title']}" + (f"\n     {'':<13} {c['detail']}" if c["detail"] and (c["level"] != "ok" or args.verbose) else ""))
            if c.get("fix") and c["level"] in ("warn", "fail"):
                print(f"     {'':<13} fix: {c['fix']}")
        if report:
            n = report["counts"]
            print(f"\n{n['ok']} ok, {n['warn']} warning(s), {n['fail']} problem(s), {n['note']} note(s)" + ("" if args.verbose else "  (-v lists the ok checks)"))
    failed = not all(ok for _, ok, _ in checks) or bool(report and not report["ok"])
    return 1 if failed else 0


def cmd_inventory(args: argparse.Namespace) -> int:
    """`aihub doctor --inventory` (plan 16.3): every path outside the project, with its reason."""
    try:
        inv = call("GET", "/api/doctor/inventory", timeout=60)
    except (HubDown, ApiError) as e:
        print(f"aihub doctor --inventory: {e}")
        return 1
    if args.json:
        print(json.dumps(inv, indent=1))
        return 0 if inv["ok"] else 1
    mark = {"allowlisted": "ok ", "runtime": "·  ", "outside": "BAD"}
    for it in sorted(inv["items"], key=lambda i: ({"outside": 0, "runtime": 1, "allowlisted": 2}[i["kind"]], i["used_by"])):
        print(f"{mark[it['kind']]}  {it['used_by']:<10} {it['path']}\n     {'':<10} {it['reason']}")
    c = inv["counts"]
    print(f"\n{c['allowlisted']} allowlisted, {c['runtime']} runtime leftover(s), {c['outside']} outside the allowlist")
    return 0 if inv["ok"] else 1


# --- entry --------------------------------------------------------------------


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="aihub", description="Control AIHub and its mods.")
    sub = ap.add_subparsers(dest="cmd", required=True, metavar="command")

    p = sub.add_parser("serve", help="run the hub in the foreground (python app.py)")
    p.add_argument("rest", nargs=argparse.REMAINDER, help="passed to app.py (--port, --dev, ...)")
    p.set_defaults(fn=cmd_serve)
    p = sub.add_parser("install", help="install and start the aihub systemd user service, or (with an id) run a mod's install.sh")
    p.add_argument("id", nargs="?")
    p.set_defaults(fn=cmd_install)
    sub.add_parser("uninstall", help="stop and remove the aihub service").set_defaults(fn=cmd_uninstall)
    for name, fn, what in (("start", cmd_start, "start"), ("stop", cmd_stop, "stop"), ("restart", cmd_restart, "restart")):
        p = sub.add_parser(name, help=f"{what} the hub (no id), a mod, or everything (all)")
        p.add_argument("id", nargs="?")
        p.set_defaults(fn=fn)
    sub.add_parser("status", help="hub and mod status").set_defaults(fn=cmd_status)
    p = sub.add_parser("logs", help="the hub's log (no id) or a mod's: data/logs/<id>.log, else the journal")
    p.add_argument("id", nargs="?")
    p.add_argument("-f", "--follow", action="store_true")
    p.add_argument("--journal", action="store_true", help="read the systemd journal instead of data/logs/")
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
    p = sub.add_parser("doctor", help="check the install: venv, config, models, manifests, paths, ports, units, disk")
    p.add_argument("-v", "--verbose", action="store_true", help="also list the checks that passed")
    p.add_argument("--json", action="store_true")
    p.add_argument("--inventory", action="store_true", help="list every path outside the project, with its reason (plan 16.3)")
    p.set_defaults(fn=cmd_doctor)
    p = sub.add_parser("backup", help="databases (online copy), registry, config.toml and the mods' .env files in a dated archive")
    p.add_argument("folder", help="where to write aihub-backup-<date>.tar.gz (made if missing)")
    p.set_defaults(fn=cmd_backup)
    p = sub.add_parser("new", help="create a mod from services/_template, install it and load it")
    p.add_argument("id", help="lowercase letters, digits and -, e.g. my-mod")
    p.add_argument("--name", help="display name (default: from the id)")
    p.add_argument("--port", type=int, help="port (default: the first free one in config.toml [ports] new_mods)")
    p.add_argument("--no-install", action="store_true", help="don't run install.sh")
    p.set_defaults(fn=cmd_new)
    sub.add_parser("rescan", help="make the hub pick up added, removed or edited mod folders").set_defaults(fn=cmd_rescan)
    p = sub.add_parser("check", help="self-test a mod: manifest, command, health, OpenAPI, status, widgets, page")
    p.add_argument("id")
    p.add_argument("--start", action="store_true", help="start it first if it isn't running")
    p.set_defaults(fn=cmd_check)
    _setup().add_parser(sub)
    sub.choices["setup"].set_defaults(fn=cmd_setup)
    p = sub.add_parser("docs", help="regenerate the mods index (docs/setup/README.md) and this machine's model inventory (data/state/setup/models/)")
    p.add_argument("--check", action="store_true", help="write nothing; exit 1 if the mods index is stale or a setup doc doesn't parse")
    p.add_argument("--strict", action="store_true", help="also fail when a mod has no setup doc")
    p.set_defaults(fn=cmd_docs)
    p = sub.add_parser("models", help="the models registry: list | show <id> | scan [--add] | verify <id>… | --all")
    p.add_argument("action", choices=["list", "show", "scan", "verify"])
    p.add_argument("ids", nargs="*", metavar="id")
    p.add_argument("--kind", help="list: only these kinds (comma-separated)")
    p.add_argument("--status", help="list: only this status")
    p.add_argument("--service", help="list: only models this mod uses")
    p.add_argument("-q", help="list: search id, name, path and tags")
    p.add_argument("--problems", action="store_true", help="list: also print each model's problems")
    p.add_argument("--add", action="store_true", help="scan: register everything found, with the suggested names")
    p.add_argument("--all", action="store_true", help="verify: every model with files on disk")
    p.add_argument("--reset", action="store_true", help="verify: forget the recorded checksums and record new ones")
    p.add_argument("--no-wait", action="store_true", help="verify: queue them and return")
    p.set_defaults(fn=cmd_models)
    return ap


def ensure_config() -> None:
    """A fresh clone's first command: config.toml from config.example.toml (plan 23.11), as the hub does."""
    cfg, example = ROOT / "config.toml", CODE / "config.example.toml"
    if not cfg.exists() and example.is_file():
        try:
            shutil.copyfile(example, cfg)
        except OSError:
            pass


def main(argv: list[str] | None = None) -> int:
    ensure_config()
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
