"""Daemon settings (``data/lcpp.json``).

Stdlib only, and shaped exactly like the Settings object the web UI edits, so
``GET/PUT /api/settings`` is a straight load/validate/save with no mapping
layer to drift. Everything binds to 127.0.0.1: this is a this-machine-only
tool, so there is deliberately no host setting to get wrong.
"""

from __future__ import annotations

import copy
import json
from typing import Any

from lcpp.paths import Paths, write_atomic

HOST = "127.0.0.1"
RELAY_OWNER = "lcpp"

DEFAULTS: dict[str, Any] = {
    "daemon": {"port": 7700},
    "llama": {
        "binary": "runtime/llama.cpp/bin/current/llama-server",
        "environment": {},
        "server_params": {},
    },
    "ports": {"start": 7071, "end": 7199},
    "relay": {
        "url": "http://127.0.0.1:4000",
        "dashboard_url": "http://127.0.0.1:4000/",
        "auto_register": True,
    },
    "scan_dirs": ["models"],
}


class SettingsError(ValueError):
    def __init__(self, field: str, message: str):
        super().__init__(f"{field}: {message}")
        self.field = field
        self.message = message


def _port(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1024 <= value <= 65535:
        raise SettingsError(field, "must be an integer port within 1024–65535")
    return value


def _url(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.startswith(("http://", "https://")):
        raise SettingsError(field, "must start with http:// or https://")
    return value.rstrip("/") if field == "relay.url" else value


def _str_map(value: Any, field: str) -> dict[str, str]:
    if not isinstance(value, dict):
        raise SettingsError(field, "must be an object")
    return {str(k): str(v) for k, v in value.items()}


def _params(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SettingsError(field, "must be an object")
    out: dict[str, Any] = {}
    for key, v in value.items():
        if not isinstance(v, (str, int, float, bool)) and v is not None:
            raise SettingsError(f"{field}.{key}", "must be a string, number, boolean or null")
        out[str(key).removeprefix("--")] = v
    return out


def validate(raw: Any) -> dict[str, Any]:
    """Merge ``raw`` over the defaults and check every field. Unknown top-level
    keys are rejected so a typo in the JSON file is an error, not a no-op."""
    if not isinstance(raw, dict):
        raise SettingsError("settings", "must be a JSON object")
    unknown = set(raw) - set(DEFAULTS)
    if unknown:
        raise SettingsError(sorted(unknown)[0], "unknown setting")
    s = copy.deepcopy(DEFAULTS)
    for section in ("daemon", "llama", "ports", "relay"):
        if section in raw:
            if not isinstance(raw[section], dict):
                raise SettingsError(section, "must be an object")
            s[section].update(raw[section])
    if "scan_dirs" in raw:
        s["scan_dirs"] = raw["scan_dirs"]

    s["daemon"] = {"port": _port(s["daemon"].get("port"), "daemon.port")}
    binary = s["llama"].get("binary")
    if not isinstance(binary, str) or not binary.strip():
        raise SettingsError("llama.binary", "is required")
    s["llama"] = {
        "binary": binary.strip(),
        "environment": _str_map(s["llama"].get("environment") or {}, "llama.environment"),
        "server_params": _params(s["llama"].get("server_params") or {}, "llama.server_params"),
    }
    start = _port(s["ports"].get("start"), "ports.start")
    end = _port(s["ports"].get("end"), "ports.end")
    if start >= end:
        raise SettingsError("ports", "start must be below end")
    s["ports"] = {"start": start, "end": end}
    s["relay"] = {
        "url": _url(s["relay"].get("url"), "relay.url"),
        "dashboard_url": _url(s["relay"].get("dashboard_url"), "relay.dashboard_url"),
        "auto_register": bool(s["relay"].get("auto_register")),
    }
    dirs = s["scan_dirs"]
    if not isinstance(dirs, list) or not all(isinstance(d, str) and d.strip() for d in dirs):
        raise SettingsError("scan_dirs", "must be a list of directory paths")
    s["scan_dirs"] = [d.strip() for d in dirs]
    return s


def load(paths: Paths) -> dict[str, Any]:
    if not paths.settings_file.exists():
        return copy.deepcopy(DEFAULTS)
    try:
        raw = json.loads(paths.settings_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise SettingsError("settings", f"{paths.settings_file} is not valid JSON: {e}") from e
    return validate(raw)


def save(paths: Paths, settings: dict[str, Any]) -> dict[str, Any]:
    clean = validate(settings)
    write_atomic(paths.settings_file, json.dumps(clean, indent=2) + "\n")
    return clean


def daemon_url(settings: dict[str, Any]) -> str:
    return f"http://{HOST}:{settings['daemon']['port']}"
