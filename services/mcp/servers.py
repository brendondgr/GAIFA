"""The configured MCP servers (plan mcp-client 1.1), in `<state>/servers.json`.

    {id, name, description, transport: "stdio" | "http", command, args, cwd, env: {NAME: value}, url,
     headers: {Name: value}, enabled, risks: {tool: risk}, deny: [tool], approved: {hash, at, tools: {tool: hash}},
     origin: {app, file}}

Values in `env` and `headers` may name a secret as `${NAME}`: it is read from this mod's `.env` (then the mod's own
environment) when the server starts, and never written to `servers.json` or shown by the API.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import time
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

ID = re.compile(r"^[a-z][a-z0-9-]{1,31}$")
VAR = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")
RISKS = ("read", "write", "generate", "network", "execute", "destructive")


class ServerIn(BaseModel):
    id: str = Field(min_length=2, max_length=32, description="Lower-case letters, digits and -; tools become mcp_<id>_<tool>")
    name: str = Field("", max_length=80)
    description: str = Field("", max_length=600)
    transport: Literal["stdio", "http"] = "stdio"
    command: str | None = Field(None, max_length=500, description="stdio: the program to start (uvx, npx, a path)")
    args: list[str] = Field(default_factory=list, max_length=64)
    cwd: str | None = Field(None, max_length=1000)
    env: dict[str, str] = Field(default_factory=dict, description="Variables for the server; ${NAME} reads NAME from the mod's .env")
    url: str | None = Field(None, max_length=1000, description="http: the server's Streamable HTTP endpoint")
    headers: dict[str, str] = Field(default_factory=dict, description="http: headers; ${NAME} reads NAME from the mod's .env")
    enabled: bool = True
    skill: str | None = Field(None, max_length=64, description="A skill to read before using it (its mcp-servers names this server)")

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        if not ID.match(v):
            raise ValueError("id: 2–32 lower-case letters, digits and -, starting with a letter")
        return v

    @model_validator(mode="after")
    def _transport(self) -> ServerIn:
        if self.transport == "stdio" and not (self.command or "").strip():
            raise ValueError("a stdio server needs command")
        if self.transport == "http" and not re.match(r"^https?://", self.url or ""):
            raise ValueError("an http server needs url (http:// or https://)")
        return self


class ServerPatch(BaseModel):
    name: str | None = Field(None, max_length=80)
    description: str | None = Field(None, max_length=600)
    command: str | None = Field(None, max_length=500)
    args: list[str] | None = Field(None, max_length=64)
    cwd: str | None = None
    env: dict[str, str] | None = None
    url: str | None = Field(None, max_length=1000)
    headers: dict[str, str] | None = None
    enabled: bool | None = None
    risks: dict[str, Literal["read", "write", "generate", "network", "execute", "destructive"]] | None = None
    deny: list[str] | None = None
    skill: str | None = None


def read_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return out
    for ln in lines:
        ln = ln.strip()
        if not ln or ln.startswith("#") or "=" not in ln:
            continue
        k, v = ln.split("=", 1)
        out[k.strip().removeprefix("export ").strip()] = v.strip().strip('"').strip("'")
    return out


def expand(values: dict[str, str], secrets_: dict[str, str]) -> tuple[dict[str, str], list[str]]:
    """`${NAME}` and `${NAME:-default}` filled from the mod's .env, then its environment; the names still missing."""
    missing: list[str] = []

    def one(m: re.Match[str]) -> str:
        v = secrets_.get(m.group(1), os.environ.get(m.group(1)))
        if v is None:
            if m.group(2) is not None:
                return m.group(2)
            missing.append(m.group(1))
            return ""
        return v
    return {k: VAR.sub(one, str(v)) for k, v in values.items()}, missing


SECRETISH = re.compile(r"key|token|secret|pass|auth|cookie|bearer|credential", re.I)


def public(s: dict[str, Any]) -> dict[str, Any]:
    """A server as the API shows it: `${NAME}` references as they are; a literal value hidden when its name looks
    like a secret (KEY, TOKEN, AUTHORIZATION, …) or it looks like one (Bearer …)."""
    def hide(d: dict[str, str]) -> dict[str, str]:
        return {k: (v if VAR.fullmatch(str(v).strip()) or not (SECRETISH.search(k) or SECRETISH.search(str(v))) else "•••")
                for k, v in (d or {}).items()}
    return {**s, "env": hide(s.get("env") or {}), "headers": hide(s.get("headers") or {})}


class Servers:
    def __init__(self, state: Path, env_file: Path) -> None:
        self.state, self.env_file = state, env_file
        self.path = state / "servers.json"

    def _load(self) -> list[dict[str, Any]]:
        try:
            return json.loads(self.path.read_text()).get("servers") or []
        except (OSError, ValueError):
            return []

    def _save(self, rows: list[dict[str, Any]]) -> None:
        self.state.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(f".servers.{secrets.token_hex(3)}.part")
        tmp.write_text(json.dumps({"servers": rows}, indent=1))
        tmp.replace(self.path)

    def list(self) -> list[dict[str, Any]]:
        return self._load()

    def get(self, sid: str) -> dict[str, Any] | None:
        return next((s for s in self._load() if s["id"] == sid), None)

    def add(self, body: ServerIn, origin: dict[str, Any] | None = None) -> dict[str, Any]:
        rows = self._load()
        if any(s["id"] == body.id for s in rows):
            raise KeyError(body.id)
        row = {**body.model_dump(), "name": body.name or body.id, "risks": {}, "deny": [], "approved": None,
               "origin": origin or {"app": "gaifa"}, "added": time.strftime("%Y-%m-%d %H:%M")}
        rows.append(row)
        self._save(rows)
        return row

    def update(self, sid: str, patch: dict[str, Any]) -> dict[str, Any]:
        rows = self._load()
        for s in rows:
            if s["id"] == sid:
                changed_launch = any(k in patch for k in ("command", "args", "cwd", "env", "url", "headers"))
                s.update({k: v for k, v in patch.items() if v is not None})
                if changed_launch:
                    s["approved"] = None              # another program: its tools are looked at again
                self._save(rows)
                return s
        raise KeyError(sid)

    def remove(self, sid: str) -> bool:
        rows = self._load()
        keep = [s for s in rows if s["id"] != sid]
        if len(keep) == len(rows):
            return False
        self._save(keep)
        return True

    def secrets(self) -> dict[str, str]:
        return read_env_file(self.env_file)
