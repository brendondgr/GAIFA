"""Signing in from another device (plan lan-access 1.2): one password, a session per device.

The password is kept as scrypt (a salt of its own) in `data/state/lan/auth.json`; sessions as the hash of a random
token, with the device's label, address, first and last use, in `data/state/lan/sessions.json` (both 0600, both in
`gaifa backup`). The token itself lives only in the device's cookie (`gaifa_session`, HttpOnly, SameSite=Strict).
Wrong passwords from one address lock it out: five, then 30 s, doubling up to 15 minutes.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

COOKIE = "gaifa_session"
MIN_LENGTH = 12
FREE_TRIES = 5
LOCK_S, LOCK_MAX_S = 30.0, 900.0
_N, _R, _P = 2 ** 14, 8, 1


def _scrypt(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, maxmem=64 * 1024 * 1024, dklen=32)


def _write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, path)


def _read(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def device_label(user_agent: str) -> str:
    """A short name for a device from its User-Agent: "Safari on iPhone", "Firefox on Linux"."""
    ua = user_agent or ""
    system = next((n for k, n in (("iPhone", "iPhone"), ("iPad", "iPad"), ("Android", "Android"), ("Windows", "Windows"),
                                  ("Mac OS X", "Mac"), ("CrOS", "ChromeOS"), ("Linux", "Linux")) if k in ua), "a device")
    browser = next((n for k, n in (("Edg/", "Edge"), ("OPR/", "Opera"), ("Firefox/", "Firefox"), ("Chrome/", "Chrome"),
                                   ("Safari/", "Safari")) if k in ua), "a browser")
    return f"{browser} on {system}"


@dataclass
class Lockout:
    fails: int = 0
    until: float = 0.0


@dataclass
class Auth:
    folder: Path
    session_days: float = 30
    clock: Callable[[], float] = time.time
    locks: dict[str, Lockout] = field(default_factory=dict)

    @property
    def auth_file(self) -> Path:
        return self.folder / "auth.json"

    @property
    def sessions_file(self) -> Path:
        return self.folder / "sessions.json"

    # ---- the password

    def has_password(self) -> bool:
        return bool(_read(self.auth_file, {}).get("hash"))

    def set_password(self, password: str) -> None:
        if len(password) < MIN_LENGTH:
            raise ValueError(f"the password needs at least {MIN_LENGTH} characters")
        salt = secrets.token_bytes(16)
        _write(self.auth_file, {"salt": salt.hex(), "hash": _scrypt(password, salt).hex(), "n": _N, "set": self.clock()})
        self.sign_out_all()                       # a new password signs every device out

    def check_password(self, password: str) -> bool:
        a = _read(self.auth_file, {})
        if not a.get("hash"):
            return False
        return hmac.compare_digest(bytes.fromhex(a["hash"]), _scrypt(password, bytes.fromhex(a["salt"])))

    # ---- lockout

    def locked_for(self, addr: str) -> float:
        lock = self.locks.get(addr)
        return max(0.0, lock.until - self.clock()) if lock else 0.0

    def _failed(self, addr: str) -> None:
        lock = self.locks.setdefault(addr, Lockout())
        lock.fails += 1
        if lock.fails >= FREE_TRIES:
            lock.until = self.clock() + min(LOCK_MAX_S, LOCK_S * 2 ** (lock.fails - FREE_TRIES))

    # ---- sessions

    def _sessions(self) -> dict[str, dict[str, Any]]:
        now, keep = self.clock(), self.session_days * 86400
        all_ = _read(self.sessions_file, {})
        return {k: v for k, v in all_.items() if now - float(v.get("last", 0)) < keep}

    def sign_in(self, password: str, addr: str, user_agent: str) -> tuple[str | None, str]:
        """(token, "") on success; (None, why) when refused: "locked" or "wrong"."""
        if self.locked_for(addr):
            return None, "locked"
        if not self.check_password(password):
            self._failed(addr)
            return None, "locked" if self.locked_for(addr) else "wrong"
        self.locks.pop(addr, None)
        token = secrets.token_urlsafe(32)
        sessions = self._sessions()
        sid = secrets.token_hex(6)
        sessions[_hash(token)] = {"id": sid, "label": device_label(user_agent), "addr": addr, "first": self.clock(), "last": self.clock()}
        _write(self.sessions_file, sessions)
        return token, ""

    def session(self, token: str | None, addr: str | None = None) -> dict[str, Any] | None:
        """The device's session for a cookie, its last use brought up to date (written at most once a minute)."""
        if not token:
            return None
        sessions = self._sessions()
        s = sessions.get(_hash(token))
        if s is None:
            return None
        now = self.clock()
        if now - float(s.get("last", 0)) > 60 or (addr and s.get("addr") != addr):
            s["last"], s["addr"] = now, addr or s.get("addr")
            _write(self.sessions_file, sessions)
        return s

    def devices(self) -> list[dict[str, Any]]:
        return sorted(self._sessions().values(), key=lambda s: -float(s.get("last", 0)))

    def sign_out(self, sid: str) -> bool:
        sessions = self._sessions()
        keep = {k: v for k, v in sessions.items() if v.get("id") != sid}
        if len(keep) == len(sessions):
            return False
        _write(self.sessions_file, keep)
        return True

    def sign_out_token(self, token: str) -> None:
        sessions = self._sessions()
        if sessions.pop(_hash(token), None) is not None:
            _write(self.sessions_file, sessions)

    def sign_out_all(self) -> None:
        _write(self.sessions_file, {})
