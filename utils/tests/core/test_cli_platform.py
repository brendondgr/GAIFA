"""37.2: `aihub` on WSL2, macOS and without systemd: opening the UI, following logs, installing, and
running the hub in the background with a pidfile."""

from __future__ import annotations

import argparse
import io
import plistlib
import threading
import time

from utils import cli, cli_platform as plat


def test_open_url_on_wsl_uses_the_windows_browser(monkeypatch):
    ran = []
    monkeypatch.setattr(plat, "is_wsl", lambda: True)
    monkeypatch.setattr(plat.shutil, "which", lambda c: "/usr/bin/" + c if c == "explorer.exe" else None)
    monkeypatch.setattr(plat.subprocess, "run", lambda cmd, **kw: ran.append(cmd) or type("R", (), {"returncode": 1})())
    assert plat.open_url("http://127.0.0.1:7000/") == 0              # explorer.exe exits 1 even when it worked
    assert ran == [["explorer.exe", "http://127.0.0.1:7000/"]]


def test_open_url_on_macos(monkeypatch):
    ran = []
    monkeypatch.setattr(plat, "is_wsl", lambda: False)
    monkeypatch.setattr(plat, "is_macos", lambda: True)
    monkeypatch.setattr(plat.shutil, "which", lambda c: "/usr/bin/open" if c == "open" else None)
    monkeypatch.setattr(plat.subprocess, "run", lambda cmd, **kw: ran.append(cmd) or type("R", (), {"returncode": 0})())
    assert plat.open_url("http://x/") == 0 and ran == [["open", "http://x/"]]


def test_tail_and_follow(tmp_path):
    f = tmp_path / "m.log"
    f.write_text("".join(f"line {i}\n" for i in range(10)))
    out = io.StringIO()
    assert plat.tail(f, 3, False, out=out) == 0 and out.getvalue() == "line 7\nline 8\nline 9\n"
    out, done = io.StringIO(), threading.Event()

    def later():
        time.sleep(0.15)
        with f.open("a") as g:
            g.write("new\n")
        time.sleep(0.2)
        f.write_text("rotated\n")              # rotation: a smaller file
        time.sleep(0.2)
        done.set()

    threading.Thread(target=later).start()
    plat.tail(f, 1, True, out=out, poll_s=0.03, stop=done.is_set)
    assert out.getvalue() == "line 9\nnew\nrotated\n"


def test_wsl_without_systemd(tmp_path, monkeypatch):
    monkeypatch.setattr(plat, "systemd_running", lambda: False)
    fix = plat.wsl_systemd_fix(tmp_path / "missing.conf")
    assert "sudo tee -a /etc/wsl.conf" in fix and "wsl --shutdown" in fix
    conf = tmp_path / "wsl.conf"
    conf.write_text("[boot]\nsystemd = true\n")
    fix = plat.wsl_systemd_fix(conf)
    assert "started before that" in fix and "sudo tee" not in fix
    monkeypatch.setattr(plat, "systemd_running", lambda: True)
    assert plat.wsl_systemd_fix(conf) is None


def test_install_on_wsl_without_systemd_prints_the_fix(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "LINK", tmp_path / "bin" / "aihub")
    monkeypatch.setattr(plat, "is_macos", lambda: False)
    monkeypatch.setattr(plat, "is_wsl", lambda: True)
    monkeypatch.setattr(plat, "systemd_running", lambda: False)
    assert cli.cmd_install(argparse.Namespace(id=None)) == 1
    err = capsys.readouterr().err
    assert "systemd" in err and "wsl --shutdown" in err
    assert (tmp_path / "bin" / "aihub").is_symlink()


def test_install_on_macos_writes_the_plist_inside_the_project(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "LINK", tmp_path / "bin" / "aihub")
    monkeypatch.setattr(cli, "ROOT", tmp_path / "root")
    monkeypatch.setattr(plat, "is_macos", lambda: True)
    assert cli.cmd_install(argparse.Namespace(id=None)) == 0
    out = capsys.readouterr().out
    p = tmp_path / "root" / "data" / "state" / "hub" / "com.aihub.hub.plist"
    d = plistlib.loads(p.read_bytes())
    assert d["Label"] == "com.aihub.hub" and d["ProgramArguments"][1].endswith("app.py") and d["KeepAlive"] is True
    assert "Library/LaunchAgents/com.aihub.hub.plist" in out and "launchctl bootstrap" in out


def test_the_hub_without_systemd(tmp_path):
    code, root = tmp_path / "code", tmp_path / "root"
    code.mkdir()
    (code / "app.py").write_text("import time\ntime.sleep(30)\n")
    pid = plat.hub_start(code, root)
    try:
        assert plat.hub_pid(root) == pid and plat.hub_start(code, root) == pid     # already running: the same
    finally:
        assert plat.hub_stop(root, timeout=5)
    assert plat.hub_pid(root) is None and not plat.hub_stop(root)
