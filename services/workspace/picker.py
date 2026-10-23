"""The desktop's own folder chooser, to add a folder to an environment (plan 43.1, the user's ask: no browser of
our own that starts in the home folder).

`POST /v1/pick-folder` opens KDE's (`kdialog`) or GNOME's (`zenity`) folder chooser on this machine, starting at `/`,
and waits for the person to pick a folder or cancel. One chooser at a time. Without one (or without a display)
it answers 501 `no_picker`, and the page takes a typed path instead. It reads nothing and writes nothing itself; the
desktop's dialog may remember its last folder in its own settings, as it does when any app opens it.
"""

from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path
from typing import Any

from folders import Refused, check_folder

WAIT_S = 600.0
_lock = asyncio.Lock()


def command(start: str = "/", title: str = "Add a folder", env: dict[str, str] | None = None,
            which=shutil.which) -> list[str] | None:
    """The chooser's command line for this desktop, or None when there is none (or no display)."""
    env = os.environ if env is None else env
    if not (env.get("WAYLAND_DISPLAY") or env.get("DISPLAY")):
        return None
    kde = "KDE" in (env.get("XDG_CURRENT_DESKTOP") or "").upper()
    kdialog = ["kdialog", "--getexistingdirectory", start, "--title", title]
    zenity = ["zenity", "--file-selection", "--directory", f"--filename={start.rstrip('/')}/", f"--title={title}"]
    for cmd in ((kdialog, zenity) if kde else (zenity, kdialog)):
        if which(cmd[0]):
            return cmd
    return None


def answer(path: str) -> dict[str, Any]:
    """A picked folder: its real path and whether an environment can take it (`check_folder`)."""
    real = str(Path(os.path.realpath(path)))
    try:
        check_folder(real)
        return {"path": real, "addable": True}
    except Refused as e:
        return {"path": real, "addable": False, "why": e.detail}


async def pick_folder(start: str = "/", title: str = "Add a folder", cmd: list[str] | None = None) -> dict[str, Any]:
    """Opens the chooser and waits: `{path, addable, why?}`, or `{cancelled: true}`."""
    cmd = cmd or command(start, title)
    if cmd is None:
        raise Refused("no_picker", "there's no folder chooser on this machine (or no display for one)",
                      "install zenity or kdialog, or type the folder's path", 501)
    if _lock.locked():
        raise Refused("busy", "a folder chooser is already open", "pick a folder in it, or close it", 409)
    async with _lock:
        proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
                                                    stdin=asyncio.subprocess.DEVNULL)
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), WAIT_S)
        except (TimeoutError, asyncio.TimeoutError):
            proc.kill()
            await proc.wait()
            return {"cancelled": True}
        except asyncio.CancelledError:                    # the page went away: close the dialog too
            proc.kill()
            raise
    path = out.decode(errors="replace").strip().splitlines()[0] if proc.returncode == 0 and out.strip() else ""
    return answer(path) if path else {"cancelled": True}
