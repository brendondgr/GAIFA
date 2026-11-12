"""Plan lan-access 1.1: what counts as this machine's network, its names and the addresses to open."""

from __future__ import annotations

import socket

import pytest

from utils.config import LanCfg
from utils.lan import addresses as A

RAW = {
    "lo": [(socket.AF_INET, "127.0.0.1", "255.0.0.0")],
    "wlp194s0": [(socket.AF_INET, "192.168.1.19", "255.255.255.0"), (socket.AF_INET6, "fe80::1%wlp194s0", "ffff:ffff:ffff:ffff::")],
    "eth0": [(socket.AF_INET, "81.2.69.160", "255.255.255.0")],          # a public address: never "local"
    "docker0": [(socket.AF_INET, "172.17.0.1", "255.255.0.0")],
    "br-0ccbe0ac4be5": [(socket.AF_INET, "172.20.0.1", "255.255.0.0")],
    "tailscale0": [(socket.AF_INET, "100.121.13.40", "255.255.255.255")],
    "veth1": [(socket.AF_INET6, "fe80::2%veth1", "ffff:ffff:ffff:ffff::")],
}


def test_only_this_machines_own_network_counts():
    ifaces = A.interfaces(RAW)
    assert sorted(i.name for i in ifaces) == ["wlp194s0", "wlp194s0"]
    nets = A.networks([], ifaces)
    assert A.is_local("192.168.1.50", nets) and A.is_local("::ffff:192.168.1.50", nets) and A.is_local("fe80::abcd", nets)
    for no in ("192.168.2.50", "172.17.0.2", "172.20.0.5", "100.101.1.2", "81.2.69.161", "8.8.8.8", "127.0.0.1", "::1", "", None, "testclient"):
        assert not A.is_local(no, nets), no
    nets = A.networks(["100.64.0.0/10"], ifaces)                       # a VPN, when asked for
    assert A.is_local("100.101.1.2", nets)


def test_allow_is_never_the_internet():
    assert A.check_cidr("100.64.0.0/10") == "100.64.0.0/10" and A.check_cidr("10.0.0.0/8") == "10.0.0.0/8"
    for bad in ("8.8.8.0/24", "0.0.0.0/0", "::/0", "81.2.69.0/24", "10.0.0.0/7", "nonsense"):
        with pytest.raises(ValueError):
            A.check_cidr(bad)
    with pytest.raises(ValueError):
        LanCfg(allow=["1.1.1.0/24"])
    with pytest.raises(ValueError):
        LanCfg(bind="8.8.8.8")
    assert LanCfg(bind="192.168.1.19").bind == "192.168.1.19" and LanCfg().enabled is False


def test_names_and_the_address_to_open(monkeypatch):
    monkeypatch.setattr(A.socket, "gethostname", lambda: "Bdgr.lan")
    ifaces = A.interfaces(RAW)
    monkeypatch.setattr(A, "primary", lambda ifaces=None: A.parse_ip("192.168.1.19"))
    assert A.names(["gaifa.home"]) == ["bdgr", "bdgr.local", "gaifa.home"]
    assert {"bdgr", "bdgr.local", "192.168.1.19"} <= A.host_names([], ifaces)
    assert A.urls(7000, 7443, [], ifaces) == ["https://192.168.1.19:7443", "https://bdgr.local:7443", "http://192.168.1.19:7000", "http://bdgr.local:7000"]
    assert A.urls(7000, None, [], ifaces) == ["http://192.168.1.19:7000", "http://bdgr.local:7000"]
