"""Plan lan-access 3.1: GAIFA's own certificate authority and this machine's certificate, made with openssl."""

from __future__ import annotations

import stat
import subprocess

import pytest

from utils.lan import cert

pytestmark = pytest.mark.skipif(not cert.available(), reason="needs the openssl command")


def names_of(crt) -> str:
    return subprocess.run(["openssl", "x509", "-in", str(crt), "-noout", "-ext", "subjectAltName"], capture_output=True, text=True).stdout


def test_made_once_kept_and_signed_by_its_own_authority(tmp_path):
    crt, key = cert.ensure(tmp_path, ["bdgr", "bdgr.local"], ["192.168.1.19", "fe80::1%wlp1"], "bdgr")
    text = names_of(crt)
    assert "DNS:bdgr.local" in text and "IP Address:192.168.1.19" in text and "FE80:0:0:0:0:0:0:1" in text.upper()
    assert stat.S_IMODE(key.stat().st_mode) == 0o600 and stat.S_IMODE((tmp_path / "lan/tls/ca.key").stat().st_mode) == 0o600
    ca = cert.ca_file(tmp_path)
    r = subprocess.run(["openssl", "verify", "-CAfile", str(ca), str(crt)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    before = crt.read_bytes()
    assert cert.ensure(tmp_path, ["bdgr.local", "bdgr"], ["192.168.1.19", "fe80::1"], "bdgr")[0].read_bytes() == before   # same names: kept
    fp = cert.fingerprint(tmp_path)
    assert fp and len(fp.split(":")) == 32


def test_a_new_address_or_one_near_its_end_is_made_again(tmp_path):
    crt, _ = cert.ensure(tmp_path, ["bdgr"], ["192.168.1.19"], "bdgr")
    first, ca = crt.read_bytes(), cert.ca_file(tmp_path).read_bytes()
    crt, _ = cert.ensure(tmp_path, ["bdgr"], ["192.168.1.20"], "bdgr")          # another Wi-Fi address
    assert crt.read_bytes() != first and "192.168.1.20" in names_of(crt)
    assert cert.ca_file(tmp_path).read_bytes() == ca                            # the authority a device trusts stays
    second = crt.read_bytes()
    import time
    cert.ensure(tmp_path, ["bdgr"], ["192.168.1.20"], "bdgr", now=time.time() + (cert.SERVER_DAYS - 10) * 86400)
    assert crt.read_bytes() != second
