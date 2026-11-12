"""Plan lan-access 2.1: `gaifa lan` against a fake hub (nothing restarts, no firewall is touched)."""

from __future__ import annotations

import argparse

import pytest

from utils import cli, cli_lan


class FakeHub:
    def __init__(self) -> None:
        self.st = {"enabled": False, "has_password": False, "listening": False, "port": 7000, "https": "also", "https_port": 7443,
                   "urls": [], "devices": []}
        self.calls: list[tuple[str, str, object]] = []
        self.restarts = 0

    def call(self, method, path, body=None, timeout=10):
        self.calls.append((method, path, body))
        if path == "/api/lan/status":
            return self.st
        if path == "/api/lan/password":
            self.st["has_password"] = True
            return {"ok": True}
        if path == "/api/lan/settings":
            self.st["enabled"] = body["enabled"]
            return {**self.st, "restart_required": True}
        if path.startswith("/api/lan/sessions/"):
            return {"ok": True}
        raise AssertionError(path)


@pytest.fixture
def hub(monkeypatch):
    h = FakeHub()
    monkeypatch.setattr(cli, "call", h.call)

    def restart(args):
        h.restarts += 1
        h.st.update(listening=h.st["enabled"], urls=["http://192.168.1.19:7000"] if h.st["enabled"] else [])
        return 0
    monkeypatch.setattr(cli, "cmd_restart", restart)
    monkeypatch.setattr(cli, "wait_up", lambda s=20: True)
    monkeypatch.setattr(cli_lan, "_firewall", lambda ports: "sudo firewall-cmd --permanent " + " ".join(f"--add-port={p}/tcp" for p in ports))
    cli_lan.cli = cli
    return h


def run(**kw) -> int:
    return cli_lan.cmd(argparse.Namespace(**{"lan_cmd": None, "json": False, "id": None, "all": False, **kw}))


def test_on_asks_for_a_password_first_then_restarts_and_says_what_to_open(hub, monkeypatch, capsys):
    monkeypatch.setattr(cli_lan.sys.stdin, "isatty", lambda: True)
    answers = iter(["short", "a long enough password", "a long enough password"])
    monkeypatch.setattr(cli_lan.getpass, "getpass", lambda prompt="": next(answers))
    assert run(lan_cmd="on") == 0
    out = capsys.readouterr().out
    assert ("PUT", "/api/lan/password", {"password": "a long enough password"}) in hub.calls
    assert ("PUT", "/api/lan/settings", {"enabled": True}) in hub.calls and hub.restarts == 1
    assert "http://192.168.1.19:7000" in out and "--add-port=7000/tcp --add-port=7443/tcp" in out and "too short" in out


def test_off_status_devices_and_signout(hub, capsys):
    hub.st.update(enabled=True, has_password=True, listening=True, urls=["http://192.168.1.19:7000"],
                  devices=[{"id": "abc", "label": "Safari on iPhone", "addr": "192.168.1.50", "first": 0, "last": 0}])
    assert run(lan_cmd="status") == 0
    assert "Safari on iPhone" in capsys.readouterr().out
    assert run(lan_cmd="signout", id="abc") == 0 and ("DELETE", "/api/lan/sessions/abc", None) in hub.calls
    assert run(lan_cmd="signout", all=True) == 0 and ("DELETE", "/api/lan/sessions/all", None) in hub.calls
    assert run(lan_cmd="signout") == 2
    assert run(lan_cmd="off") == 0 and hub.restarts == 1
    assert "this machine only" in capsys.readouterr().out


def test_a_password_is_never_an_argument(hub, monkeypatch, capsys):
    monkeypatch.setattr(cli_lan.sys.stdin, "isatty", lambda: False)
    assert run(lan_cmd="password") == 2
    assert "never an argument" in capsys.readouterr().err
