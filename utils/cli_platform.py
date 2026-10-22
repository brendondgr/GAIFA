"""What `aihub` does differently on WSL2 and macOS (plan 37.2). Standard library only.

- **Opening the UI:** WSL2 opens the Windows browser (`wslview`, else `explorer.exe`), macOS uses
  `open`, Linux `xdg-open`, anything else Python's `webbrowser`.
- **Logs:** followed in Python, not `tail -F`.
- **The hub as a service:**
  - **Linux:** systemd, as before.
  - **WSL2:** systemd too, once it's on in `/etc/wsl.conf` (the fix is printed when it's off).
  - **macOS:** a launchd agent. Its plist is written inside the project (`data/state/hub/`), and the
    commands that place and load it are printed for the person: nothing is written outside the
    project.
  - **Without systemd:** the hub runs detached, with a pidfile (`data/state/hub/aihub.json`), for
    `start`, `stop` and `status`.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import signal
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

LABEL = "com.aihub.hub"
WSL_CONF = Path("/etc/wsl.conf")


def is_wsl() -> bool:
    try:
        v = Path("/proc/version").read_text().lower()
    except OSError:
        return False
    return "microsoft" in v or "wsl" in v


def is_macos() -> bool:
    return platform.system() == "Darwin"


def systemd_running() -> bool:
    """systemd is the init system here (so `systemctl --user` can work)."""
    return Path("/run/systemd/system").is_dir() and shutil.which("systemctl") is not None


def wsl_systemd_fix(conf: Path = WSL_CONF) -> str | None:
    """None when WSL runs systemd, else what to do about it."""
    if systemd_running():
        return None
    try:
        text = conf.read_text()
    except OSError:
        text = ""
    has = any(line.replace(" ", "").lower() == "systemd=true" for line in text.splitlines())
    head = ("/etc/wsl.conf turns systemd on, but this WSL session started before that"
            if has else "WSL runs without systemd")
    return (f"{head}. AIHub runs as a systemd user service, so turn it on:\n"
            + ("" if has else "  printf '[boot]\\nsystemd=true\\n' | sudo tee -a /etc/wsl.conf\n")
            + "  then, in Windows (PowerShell): wsl --shutdown   and open Ubuntu again.\n"
            "Until then, `aihub start` runs the hub without systemd (it stops when WSL shuts down).")


def open_url(url: str) -> int:
    if is_wsl():
        for cmd in (["wslview", url], ["explorer.exe", url]):
            if shutil.which(cmd[0]):
                subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return 0          # explorer.exe exits 1 even when it opened the page
    elif is_macos() and shutil.which("open"):
        return subprocess.run(["open", url]).returncode
    elif shutil.which("xdg-open"):
        return subprocess.run(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode
    if not webbrowser.open(url):
        print(url)
    return 0


def tail(path: Path, n: int, follow: bool, out=sys.stdout, poll_s: float = 0.3, stop=lambda: False) -> int:
    """The last `n` lines of a file, then (with `follow`) what's added to it, across rotation."""
    try:
        with path.open("rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - 512 * 1024))
            lines = f.read().split(b"\n")
    except OSError as e:
        print(f"aihub: {path}: {e.strerror}", file=sys.stderr)
        return 1
    for raw in [x for x in lines[:-1]][-n:] if n > 0 else []:
        out.write(raw.decode(errors="replace") + "\n")
    out.flush()
    if not follow:
        return 0
    pos = path.stat().st_size
    try:
        while not stop():
            try:
                size = path.stat().st_size
            except OSError:
                size = 0
            if size < pos:              # rotated or truncated: read the new file from its start
                pos = 0
            if size > pos:
                with path.open("rb") as f:
                    f.seek(pos)
                    chunk = f.read(size - pos)
                pos += len(chunk)
                out.write(chunk.decode(errors="replace"))
                out.flush()
            time.sleep(poll_s)
    except KeyboardInterrupt:
        pass
    return 0


# --- macOS: launchd ---------------------------------------------------------------------


def plist(code: Path, root: Path) -> str:
    py = code / ".venv" / "bin" / "python"
    log = root / "data" / "logs" / "aihub.launchd.log"
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>{LABEL}</string>
  <key>ProgramArguments</key><array><string>{py}</string><string>{code / 'app.py'}</string></array>
  <key>WorkingDirectory</key><string>{code}</string>
  <key>EnvironmentVariables</key><dict><key>AIHUB_ROOT</key><string>{root}</string></dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>{log}</string>
  <key>StandardErrorPath</key><string>{log}</string>
</dict>
</plist>
"""


def launchd_install(code: Path, root: Path) -> tuple[Path, list[str]]:
    """Write the plist inside the project; return it and the commands that place and load it."""
    here = root / "data" / "state" / "hub" / f"{LABEL}.plist"
    here.parent.mkdir(parents=True, exist_ok=True)
    here.write_text(plist(code, root))
    dest = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
    uid = os.getuid() if hasattr(os, "getuid") else 0
    return here, [f"mkdir -p {dest.parent}", f"cp {here} {dest}", f"launchctl bootstrap gui/{uid} {dest}",
                  f"launchctl kickstart -k gui/{uid}/{LABEL}"]


# --- the hub without systemd: a pidfile ------------------------------------------------------


def _pidfile(root: Path) -> Path:
    return root / "data" / "state" / "hub" / "aihub.json"


def hub_pid(root: Path) -> int | None:
    """The detached hub's pid while it runs (its pidfile, checked against the process's command)."""
    try:
        rec = json.loads(_pidfile(root).read_text())
        pid = int(rec["pid"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return None
    try:
        cmd = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
        if "app.py" not in cmd:
            return None
    except OSError:
        pass      # no /proc (macOS): the pid's liveness is all there is
    return pid


def hub_start(code: Path, root: Path, args: list[str] | None = None) -> int:
    if hub_pid(root):
        return hub_pid(root) or 0
    out = root / "data" / "state" / "hub" / "aihub.out"
    out.parent.mkdir(parents=True, exist_ok=True)
    py = code / ".venv" / "bin" / "python"
    with out.open("ab") as f:
        p = subprocess.Popen([str(py if py.exists() else sys.executable), str(code / "app.py"), *(args or [])], cwd=code,
                             env={**os.environ, "AIHUB_ROOT": str(root)}, stdin=subprocess.DEVNULL, stdout=f, stderr=subprocess.STDOUT,
                             start_new_session=True)
    _pidfile(root).write_text(json.dumps({"pid": p.pid, "started_ts": time.time()}))
    return p.pid


def hub_stop(root: Path, timeout: float = 20) -> bool:
    pid = hub_pid(root)
    if pid is None:
        _pidfile(root).unlink(missing_ok=True)
        return False
    os.kill(pid, signal.SIGTERM)
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.2)
    else:
        os.kill(pid, signal.SIGKILL)
    _pidfile(root).unlink(missing_ok=True)
    return True
