"""What stays on this machine (plan lan-access 1.5): a signed-in device on the network can use GAIFA as the page
here does, except for what would widen what GAIFA may do or who may reach it.

- the network settings, the password and the devices (`/api/lan/*` writes), and the hub's own settings (`hub` in
  `PUT /api/settings`: its port);
- a chat, project or task in Bypass (any `"mode": "bypass"` sent to the agent);
- a workspace folder's level or Bypass (`level` above Read, or `"bypass": true`, sent to a folder route);
- `/mcp` (Claude Code and Codex on this machine only).

`refused(method, path, body)` says why, or None. The body is the request's JSON (None when it has none or isn't JSON).
"""

from __future__ import annotations

import re
from typing import Any

UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}
FOLDER_PATH = re.compile(r"^/api/s/(workspace/v1/(folders|environments/[^/]+/folders)|agent/v1/projects/[^/]+/folders)(/|$)")
WHERE = "Do this on the GAIFA machine itself (http://127.0.0.1:7000)."


def _walk(x: Any):
    if isinstance(x, dict):
        for k, v in x.items():
            yield k, v
            yield from _walk(v)
    elif isinstance(x, list):
        for v in x:
            yield from _walk(v)


def needs_body(method: str, path: str) -> bool:
    """Whether `refused` has to read this request's body."""
    return method in UNSAFE and (path.startswith("/api/s/agent/") or bool(FOLDER_PATH.match(path)) or path == "/api/settings")


def refused(method: str, path: str, body: Any = None) -> str | None:
    if path == "/mcp" or path.startswith("/mcp/"):
        return "GAIFA's MCP server is for coding agents on the GAIFA machine only."
    if method not in UNSAFE:
        return None
    if path == "/api/system/restart":
        return f"GAIFA can only be restarted from the GAIFA machine. {WHERE}"
    if path.startswith("/api/lan/") and path not in ("/api/lan/signin", "/api/lan/signout"):
        return f"The network settings, the password and the devices signed in can only be changed on the GAIFA machine. {WHERE}"
    if path == "/api/settings" and isinstance(body, dict) and "hub" in body:
        return f"The hub's own settings can only be changed on the GAIFA machine. {WHERE}"
    if path.startswith("/api/s/agent/") and any(k == "mode" and v == "bypass" for k, v in _walk(body)):
        return f"Bypass (nothing asks first) can only be turned on from the GAIFA machine. {WHERE}"
    if FOLDER_PATH.match(path):
        for k, v in _walk(body):
            if k == "bypass" and v is True:
                return f"A folder's Bypass can only be turned on from the GAIFA machine. {WHERE}"
            if k == "level" and v not in (None, "read", "none", "off"):
                return f"A folder's level can only be raised above Read from the GAIFA machine. {WHERE}"
    return None
