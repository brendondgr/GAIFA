"""GAIFA from other devices on your network (plan lan-access): off by default.

With `[hub.lan] enabled` and a password set, the hub listens on every address (plan 1.4) and `guard.py` lets in
only devices on this machine's own network that have signed in; this machine (loopback) is never asked anything,
and mods stay on loopback. `Lan` holds what the guard and the routes read: the settings, the networks and names
(found again every 30 s, so a new Wi-Fi address is followed), and the sign-in (`auth.py`).
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from utils.lan import addresses
from utils.lan.auth import Auth

REFRESH_S = 30.0


class Lan:
    def __init__(self, cfg: Any, state_dir: Path, hub_port: int, ifaces: list[addresses.Iface] | None = None) -> None:
        self.cfg = cfg                                    # utils.config.LanCfg
        self.hub_port = hub_port
        self.auth = Auth(state_dir / "lan", session_days=cfg.session_days)
        self.listening = False                            # app.py bound the network sockets
        self.https_listening = False                      # app.py serves HTTPS on https_port (Phase 3)
        self._fixed = ifaces                              # tests
        self._at = 0.0
        self._nets: list[addresses.Net] = []
        self._hosts: set[str] = set()

    def reconfigure(self, cfg: Any) -> None:
        self.cfg = cfg
        self.auth.session_days = cfg.session_days
        self._at = 0.0

    @property
    def on(self) -> bool:
        """Devices on the network may sign in: turned on, with a password, and listening."""
        return bool(self.cfg.enabled and self.listening and self.auth.has_password())

    @property
    def https_port(self) -> int | None:
        return self.cfg.https_port if self.https_listening else None

    def _refresh(self) -> None:
        if self._fixed is None and time.monotonic() - self._at < REFRESH_S and self._at:
            return
        ifaces = self._fixed if self._fixed is not None else addresses.interfaces()
        self._nets = addresses.networks(self.cfg.allow, ifaces)
        self._hosts = addresses.host_names(self.cfg.names, ifaces)
        self._at = time.monotonic()

    def is_local(self, client: str | None) -> bool:
        self._refresh()
        return addresses.is_local(client, self._nets)

    def hosts(self) -> set[str]:
        self._refresh()
        return self._hosts

    def ports(self) -> set[int]:
        return {self.hub_port, *([self.https_port] if self.https_port else [])}

    def urls(self) -> list[str]:
        ifaces = self._fixed if self._fixed is not None else addresses.interfaces()
        return addresses.urls(self.hub_port, self.https_port, self.cfg.names, ifaces)

    def status(self) -> dict[str, Any]:
        return {"enabled": self.cfg.enabled, "listening": self.listening, "on": self.on, "has_password": self.auth.has_password(),
                "urls": self.urls() if self.cfg.enabled else [], "port": self.hub_port, "https": self.cfg.https,
                "https_port": self.cfg.https_port, "allow": list(self.cfg.allow), "names": list(self.cfg.names),
                "session_days": self.cfg.session_days, "devices": self.auth.devices()}
