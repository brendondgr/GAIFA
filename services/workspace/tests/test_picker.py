"""Plan 43.1: the desktop's folder chooser: which command per desktop, a pick, a cancel, no chooser, one at a time, and
a folder an environment can't take. The chooser is faked with a small command."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

import picker


def test_the_command_per_desktop():
    have = lambda *names: (lambda n: f"/usr/bin/{n}" if n in names else None)       # noqa: E731
    kde = {"WAYLAND_DISPLAY": "wayland-0", "XDG_CURRENT_DESKTOP": "KDE"}
    gnome = {"DISPLAY": ":0", "XDG_CURRENT_DESKTOP": "GNOME"}
    assert picker.command("/", "Add", kde, have("kdialog", "zenity"))[:3] == ["kdialog", "--getexistingdirectory", "/"]
    assert picker.command("/", "Add", gnome, have("kdialog", "zenity"))[:4] == ["zenity", "--file-selection", "--directory", "--filename=/"]
    assert picker.command("/", "Add", kde, have("zenity"))[0] == "zenity"                    # whichever is installed
    assert picker.command("/", "Add", kde, have()) is None                                    # none installed
    assert picker.command("/", "Add", {"XDG_CURRENT_DESKTOP": "KDE"}, have("kdialog")) is None   # no display


def fake(script: str) -> list[str]:
    return [sys.executable, "-c", script]


def test_a_pick_a_cancel_and_a_folder_that_cant_be_added(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    got = asyncio.run(picker.pick_folder(cmd=fake(f"print({str(proj)!r})")))
    assert got == {"path": str(proj), "addable": True}
    assert asyncio.run(picker.pick_folder(cmd=fake("import sys; sys.exit(1)"))) == {"cancelled": True}
    home = asyncio.run(picker.pick_folder(cmd=fake(f"print({str(Path.home())!r})")))
    assert home["addable"] is False and "too broad" in home["why"]


def test_no_chooser_and_one_at_a_time(monkeypatch):
    monkeypatch.setattr(picker, "command", lambda *a, **k: None)
    with pytest.raises(picker.Refused) as e:
        asyncio.run(picker.pick_folder())
    assert e.value.code == "no_picker" and e.value.status == 501

    async def two():
        first = asyncio.create_task(picker.pick_folder(cmd=fake("import time; time.sleep(0.5); print('/tmp')")))
        await asyncio.sleep(0.1)
        with pytest.raises(picker.Refused) as busy:
            await picker.pick_folder(cmd=fake("print('/tmp')"))
        assert busy.value.code == "busy" and busy.value.status == 409
        return await first
    assert asyncio.run(two())["path"] == str(Path("/tmp").resolve())


def test_the_route(client, monkeypatch, tmp_path):
    proj = tmp_path / "proj2"
    proj.mkdir()
    monkeypatch.setattr(picker, "command", lambda start, title: fake(f"print({str(proj)!r})") if start == "/" else None)
    r = client.post("/v1/pick-folder", json={})
    assert r.status_code == 200 and r.json() == {"path": str(proj), "addable": True}
    r = client.post("/v1/pick-folder", json={"start": "/elsewhere"})
    assert r.status_code == 501 and r.json()["code"] == "no_picker"
