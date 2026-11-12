"""Plan lan-access 1.4: the sockets the hub listens on, per [hub.lan]."""

from __future__ import annotations

import socket

import app as app_py
from utils.config import LanCfg


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def names(socks):
    out = sorted(s.getsockname()[0] for s in socks)
    for s in socks:
        s.close()
    return out


def test_closed_or_without_a_password_it_is_loopback_only():
    port = _free_port()
    assert app_py.lan_sockets(LanCfg(), port, True) is None
    assert app_py.lan_sockets(LanCfg(enabled=True), port, False) is None


def test_open_it_listens_on_every_address_or_on_one():
    port = _free_port()
    assert "0.0.0.0" in names(app_py.lan_sockets(LanCfg(enabled=True), port, True))
    socks = app_py.lan_sockets(LanCfg(enabled=True, bind="10.255.255.254"), _free_port(), True)   # not this machine's: can't bind
    assert socks is None


def test_a_taken_port_is_a_warning_not_a_failed_start(caplog):
    with socket.socket() as busy:
        busy.bind(("0.0.0.0", 0))
        busy.listen()
        assert app_py.lan_sockets(LanCfg(enabled=True), busy.getsockname()[1], True) is None
    assert "stays on this machine only" in caplog.text
