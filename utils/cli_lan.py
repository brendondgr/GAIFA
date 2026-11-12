"""`gaifa lan`: open GAIFA to other devices on your network, or close it (plan lan-access 2.1). Standard library only.

    gaifa lan [status]          on or off, the addresses to open, the devices signed in
    gaifa lan on                asks for a password when none is set, turns it on, restarts GAIFA, says what to open
    gaifa lan off               closes it (restarts GAIFA)
    gaifa lan password          sets the password devices sign in with (every device signs in again)
    gaifa lan devices           the devices signed in
    gaifa lan signout <id>|--all
"""

from __future__ import annotations

import argparse
import getpass
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

cli: Any = None          # utils/cli.py, set by its loader

MIN_LENGTH = 12


def _ago(ts: float | None) -> str:
    import time

    if not ts:
        return "never"
    s = max(0, time.time() - float(ts))
    return "just now" if s < 90 else f"{int(s // 60)} min ago" if s < 3600 else f"{int(s // 3600)} h ago" if s < 86400 else f"{int(s // 86400)} d ago"


def _ask_password() -> str | None:
    if not sys.stdin.isatty():
        print("gaifa lan: the password is asked for on a terminal (it is never an argument)", file=sys.stderr)
        return None
    while True:
        pw = getpass.getpass(f"Password for other devices (at least {MIN_LENGTH} characters): ")
        if len(pw) < MIN_LENGTH:
            print(f"  too short: at least {MIN_LENGTH} characters")
            continue
        if getpass.getpass("Again: ") != pw:
            print("  they differ; once more")
            continue
        return pw


def _set_password(pw: str) -> None:
    try:
        cli.call("PUT", "/api/lan/password", {"password": pw}, timeout=30)
    except cli.HubDown:                                      # the hub isn't running: write it here (stdlib only)
        here = str(Path(__file__).resolve().parent.parent)
        if here not in sys.path:
            sys.path.insert(0, here)
        from utils.lan.auth import Auth

        Auth(cli.ROOT / "data" / "state" / "lan").set_password(pw)


def _firewall(ports: list[int]) -> str | None:
    """The command that opens the ports, for the firewall this machine runs (GAIFA never runs sudo)."""
    if shutil.which("firewall-cmd"):
        r = subprocess.run(["firewall-cmd", "--state"], capture_output=True, text=True)
        if r.returncode == 0 and "running" in r.stdout:
            adds = " ".join(f"--add-port={p}/tcp" for p in ports)
            return f"sudo firewall-cmd --permanent {adds} && sudo firewall-cmd --reload"
    if shutil.which("ufw"):
        return " && ".join(f"sudo ufw allow {p}/tcp" for p in ports)
    return None


def _print_status(st: dict[str, Any]) -> None:
    if not st.get("enabled"):
        print("GAIFA answers this machine only (gaifa lan on opens it to your network).")
        return
    if not st.get("has_password"):
        print("Opened to the network, but no password is set: gaifa lan password")
    elif not st.get("listening"):
        print("Opened to the network, but not listening on it yet: gaifa restart")
    else:
        print("Open to your network. On another device, open:")
        for u in st.get("urls", [])[:3]:
            print(f"  {u}")
    devices = st.get("devices", [])
    print(f"{len(devices)} device(s) signed in" + (":" if devices else "."))
    for d in devices:
        print(f"  {d['id']}  {d['label']:<24} {d['addr']:<16} last used {_ago(d.get('last'))}")


def cmd(args: argparse.Namespace) -> int:
    action = args.lan_cmd or "status"
    try:
        if action == "password":
            pw = _ask_password()
            if pw is None:
                return 2
            _set_password(pw)
            print("Password set; every device signs in again.")
            return 0
        st = cli.call("GET", "/api/lan/status")
        if action == "status":
            if args.json:
                print(json.dumps(st, indent=1))
            else:
                _print_status(st)
            return 0
        if action == "devices":
            for d in st.get("devices", []):
                print(f"{d['id']}  {d['label']:<24} {d['addr']:<16} last used {_ago(d.get('last'))}")
            return 0
        if action == "signout":
            if not args.all and not args.id:
                print("gaifa lan signout <id> | --all", file=sys.stderr)
                return 2
            cli.call("DELETE", f"/api/lan/sessions/{'all' if args.all else cli.q(args.id)}")
            print("Signed out.")
            return 0
        if action in ("on", "off"):
            on = action == "on"
            if on and not st.get("has_password"):
                pw = _ask_password()
                if pw is None:
                    return 2
                _set_password(pw)
            r = cli.call("PUT", "/api/lan/settings", {"enabled": on})
            if r.get("restart_required"):
                print("Restarting GAIFA…")
                cli.cmd_restart(argparse.Namespace(id=None))
                cli.wait_up(30)
            st = cli.call("GET", "/api/lan/status")
            _print_status(st)
            if on:
                ports = [st["port"], *([st["https_port"]] if st.get("https") != "off" else [])]
                fw = _firewall(ports)
                print("\nIf other devices can't reach it, this machine's firewall blocks the port. Opening it is yours to run:"
                      if fw else "\nIf other devices can't reach it, open TCP port(s) " + ", ".join(map(str, ports)) + " in this machine's firewall.")
                if fw:
                    print(f"  {fw}")
                print("Only devices on your own network get in, and only with the password.")
            return 0
    except cli.HubDown as e:
        print(f"gaifa lan: {e}", file=sys.stderr)
        return 1
    except cli.ApiError as e:
        print(f"gaifa lan: {e.detail}", file=sys.stderr)
        return 1
    print(f"gaifa lan: unknown action {action!r}", file=sys.stderr)
    return 2


def add_parser(sub: Any) -> None:
    p = sub.add_parser("lan", help="other devices on your network: status | on | off | password | devices | signout")
    ls = p.add_subparsers(dest="lan_cmd", metavar="action")
    s = ls.add_parser("status", help="on or off, the addresses to open, the devices signed in")
    s.add_argument("--json", action="store_true")
    ls.add_parser("on", help="open GAIFA to your network (asks for a password when none is set; restarts GAIFA)")
    ls.add_parser("off", help="close it again (restarts GAIFA)")
    ls.add_parser("password", help="set the password devices sign in with (asked for; every device signs in again)")
    ls.add_parser("devices", help="the devices signed in")
    so = ls.add_parser("signout", help="sign a device out")
    so.add_argument("id", nargs="?")
    so.add_argument("--all", action="store_true")
    p.set_defaults(fn=cmd, json=False)
