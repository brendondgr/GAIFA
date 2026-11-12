"""Plan lan-access 1.2: the password, a session per device, its life, and the lockout."""

from __future__ import annotations

import stat

import pytest

from utils.lan.auth import Auth, device_label


class Clock:
    def __init__(self) -> None:
        self.t = 1_000_000.0

    def __call__(self) -> float:
        return self.t


def test_a_password_signs_a_device_in_and_a_session_lives_as_long_as_it_is_used(tmp_path):
    clock = Clock()
    a = Auth(tmp_path / "lan", session_days=1, clock=clock)
    assert not a.has_password()
    with pytest.raises(ValueError):
        a.set_password("short")
    a.set_password("correct horse battery")
    assert a.has_password() and a.check_password("correct horse battery") and not a.check_password("correct horse batterY")
    assert "correct horse" not in a.auth_file.read_text()                     # only the hash is kept
    assert stat.S_IMODE(a.auth_file.stat().st_mode) == 0o600
    token, why = a.sign_in("correct horse battery", "192.168.1.50", "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0) Safari/604.1")
    assert token and why == ""
    assert token not in a.sessions_file.read_text()                           # the cookie's token is never stored
    s = a.session(token, "192.168.1.50")
    assert s["label"] == "Safari on iPhone" and s["addr"] == "192.168.1.50"
    clock.t += 20 * 3600
    assert a.session(token) is not None                                       # used: its day starts again
    clock.t += 20 * 3600
    assert a.session(token) is not None
    clock.t += 25 * 3600                                                       # a day unused: gone
    assert a.session(token) is None and a.devices() == []


def test_sign_out_one_all_and_a_new_password(tmp_path):
    a = Auth(tmp_path / "lan")
    a.set_password("a long enough password")
    t1, _ = a.sign_in("a long enough password", "192.168.1.50", "Firefox/130 Linux")
    t2, _ = a.sign_in("a long enough password", "192.168.1.51", "Chrome/130 Windows")
    assert [d["label"] for d in a.devices()] in (["Firefox on Linux", "Chrome on Windows"], ["Chrome on Windows", "Firefox on Linux"])
    sid = a.session(t1)["id"]
    assert a.sign_out(sid) and not a.sign_out(sid) and a.session(t1) is None and a.session(t2) is not None
    a.set_password("another long password")                                   # every device signs in again
    assert a.session(t2) is None


def test_wrong_passwords_lock_an_address_out(tmp_path):
    clock = Clock()
    a = Auth(tmp_path / "lan", clock=clock)
    a.set_password("a long enough password")
    for _ in range(4):
        assert a.sign_in("nope", "192.168.1.66", "") == (None, "wrong")
    assert a.sign_in("nope", "192.168.1.66", "") == (None, "locked")
    assert a.sign_in("a long enough password", "192.168.1.66", "") == (None, "locked")     # even the right one, for now
    assert a.sign_in("a long enough password", "192.168.1.67", "")[0]                     # another address isn't
    clock.t += 31
    assert a.sign_in("nope", "192.168.1.66", "") == (None, "locked") and 59 <= a.locked_for("192.168.1.66") <= 60   # doubling
    clock.t += 61
    assert a.sign_in("a long enough password", "192.168.1.66", "")[0]
    assert device_label("") == "a browser on a device"
