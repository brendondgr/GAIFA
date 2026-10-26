"""MCP servers other apps on this machine already configure (plan mcp-client 3.1), read only when asked.

Each app keeps them in its own file: Claude Code (`~/.claude.json`: user-wide `mcpServers`, and per project
`projects[<path>].mcpServers`), Claude Desktop, Cursor (`~/.cursor/mcp.json`), Codex (`~/.codex/config.toml`
`[mcp_servers.<name>]`), Gemini CLI (`~/.gemini/settings.json`), VS Code (`mcp.json`, `servers`), and a project's own
`.mcp.json`, `.cursor/mcp.json` or `.vscode/mcp.json` in a workspace folder. What is found: the name, the command and
its arguments or the URL, and the *names* of its environment variables and headers, never their values: an imported
server names them as `${NAME}`, for the user to put in `services/mcp/.env`.
"""

from __future__ import annotations

import hashlib
import json
import re
import tomllib
from pathlib import Path
from typing import Any

HOME = Path.home()
APPS = [
    ("Claude Code", HOME / ".claude.json", "claude_code"),
    ("Claude Desktop", HOME / ".config" / "Claude" / "claude_desktop_config.json", "mcpServers"),
    ("Claude Desktop", HOME / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json", "mcpServers"),
    ("Cursor", HOME / ".cursor" / "mcp.json", "mcpServers"),
    ("Codex", HOME / ".codex" / "config.toml", "codex"),
    ("Gemini CLI", HOME / ".gemini" / "settings.json", "mcpServers"),
    ("VS Code", HOME / ".config" / "Code" / "User" / "mcp.json", "servers"),
]
PROJECT_FILES = [(".mcp.json", "mcpServers"), (".cursor/mcp.json", "mcpServers"), (".vscode/mcp.json", "servers")]


def _entry(app: str, file: Path, name: str, cfg: dict[str, Any], scope: str = "user") -> dict[str, Any] | None:
    if not isinstance(cfg, dict):
        return None
    url = cfg.get("url") or cfg.get("httpUrl") or cfg.get("serverUrl")
    command = cfg.get("command")
    if isinstance(command, list):                       # opencode's ["uvx", "x"]
        command, args = (command[0], command[1:]) if command else (None, [])
    else:
        args = cfg.get("args") or []
    if not command and not url:
        return None
    env = cfg.get("env") or cfg.get("environment") or {}
    headers = cfg.get("headers") or cfg.get("http_headers") or {}
    out = {"app": app, "file": str(file), "scope": scope, "name": name,
           "transport": "http" if url and not command else "stdio",
           "command": command, "args": [str(a) for a in args] if isinstance(args, list) else [], "url": url,
           "env_names": sorted(env) if isinstance(env, dict) else [], "header_names": sorted(headers) if isinstance(headers, dict) else []}
    if cfg.get("bearer_token_env_var"):                 # Codex: a token from an environment variable
        out["header_names"].append("Authorization")
        out["bearer_env"] = cfg["bearer_token_env_var"]
    out["key"] = hashlib.sha256(json.dumps([out["file"], scope, name]).encode()).hexdigest()[:12]
    return out


def _read(file: Path, kind: str) -> list[dict[str, Any]]:
    try:
        text = file.read_text()
    except OSError:
        return []
    try:
        data = tomllib.loads(text) if kind == "codex" else json.loads(text)
    except (ValueError, tomllib.TOMLDecodeError):
        return []
    app = {"claude_code": "Claude Code", "codex": "Codex"}.get(kind, "")
    out: list[dict[str, Any]] = []
    if kind == "claude_code":
        for n, c in (data.get("mcpServers") or {}).items():
            out.append(_entry(app, file, n, c))
        for proj, p in (data.get("projects") or {}).items():
            for n, c in ((p or {}).get("mcpServers") or {}).items():
                out.append(_entry(app, file, n, c, scope=f"project {proj}"))
    elif kind == "codex":
        for n, c in (data.get("mcp_servers") or {}).items():
            out.append(_entry(app, file, n, c))
    else:
        for n, c in (data.get(kind) or {}).items():
            out.append(_entry("", file, n, c))
    return [e for e in out if e]


def found(folders: list[str] = ()) -> list[dict[str, Any]]:  # type: ignore[assignment]
    """Every server the apps on this machine configure, and those in the workspace folders' project files."""
    out = []
    for app, file, kind in APPS:
        for e in _read(file, kind):
            out.append({**e, "app": e["app"] or app})
    for folder in folders:
        for rel, kind in PROJECT_FILES:
            f = Path(folder) / rel
            for e in _read(f, kind):
                out.append({**e, "app": f"project file in {Path(folder).name}", "scope": f"folder {folder}"})
    return out


def as_server(e: dict[str, Any], sid: str | None = None) -> dict[str, Any]:
    """A found server as a ServerIn body: values named, never copied."""
    sid = sid or re.sub(r"[^a-z0-9-]+", "-", e["name"].lower()).strip("-")[:32] or "server"
    if not re.match(r"^[a-z]", sid):
        sid = "s-" + sid
    body: dict[str, Any] = {"id": sid[:32], "name": e["name"], "transport": e["transport"],
                            "description": f"Imported from {e['app']} ({e['file']}, {e['scope']})"}
    if e["transport"] == "http":
        body["url"] = e["url"]
        body["headers"] = {h: "${" + re.sub(r"[^A-Z0-9_]", "_", h.upper()) + "}" for h in e["header_names"]}
        if e.get("bearer_env"):
            body["headers"]["Authorization"] = "Bearer ${" + e["bearer_env"] + "}"
    else:
        body.update(command=e["command"], args=e["args"])
    body["env"] = {n: "${" + n + "}" for n in e["env_names"]}
    return body
