"""Grants (plan 25.2): one answer that covers more than one call.

A grant allows the calls of a tool (a name glob) without a card, in one chat (`scope = "thread"`)
or everywhere (`"always"`), until it expires or is revoked. Deciding an approval with
`remember: "thread" | "always"` writes one (architecture §14.7).

**Keys.** A tool may name a grant key in its `[tools]` entry, so "allow in this chat" means "this
domain" or "this folder" rather than every call: `grant_key = "url:host"` (the host of the `url`
argument), `"arg:<name>"` (that argument as is) or `"const:<x>"` (always `x`, so one answer covers
every call of the tool, e.g. searching). A grant whose key is null covers every call of its tool.

**A mod's own key** (plan 27.4): a mod with a preflight (`[agent] limits`) may name the key itself
(`limits.key`, e.g. "itsdangerous pytest -q": the folder and the exact command line), which then
replaces the one read from the arguments. A preflight's `once` action (host runs, commits, git
remotes, and a compound command, which has no key) can't be remembered at all.

**Who it covers.** A `thread` grant covers calls whose origin names that thread (the chat); an MCP
or API call has no thread, so only `always` grants apply to it. `thread` grants end with their
thread (the agent calls `DELETE /api/grants?thread=` when a chat is deleted).
"""

from __future__ import annotations

import fnmatch
import json
import re
import secrets
import time
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from utils.db import Database
    from utils.events import EventBus
    from utils.tools.catalog import ToolDef

GRANT_KEY = re.compile(r"^(url:host|arg:[A-Za-z_][A-Za-z0-9_.-]{0,63}|const:[A-Za-z0-9_.:-]{1,64})$")
REMEMBER = ("once", "thread", "always")
CONFIRM_RISKS = ("execute", "destructive")   # an `always` grant for these needs a second confirm


def key_of(grant_key: str | None, arguments: Any) -> str | None:
    """The call's grant key from its arguments; None when the tool has none or it can't be read."""
    if not grant_key or not isinstance(arguments, dict):
        return None
    kind, _, what = grant_key.partition(":")
    if kind == "const":
        return what
    if kind == "arg":
        v = arguments.get(what)
        if v is None or v == "":
            return None
        return v if isinstance(v, str) else json.dumps(v, sort_keys=True)
    if kind == "url" and what == "host":
        v = arguments.get("url")
        try:
            host = urlsplit(v).hostname if isinstance(v, str) else None
        except ValueError:
            return None
        return host.lower().rstrip(".") if host else None
    return None


def problems(grant_key: str | None, params: dict[str, Any]) -> list[str]:
    """`aihub check`: a key that reads an argument the tool doesn't take."""
    if not grant_key:
        return []
    props = params.get("properties") or {}
    kind, _, what = grant_key.partition(":")
    if kind == "url" and "url" not in props:
        return [f"grant_key {grant_key!r} needs a `url` parameter"]
    if kind == "arg" and what not in props:
        return [f"grant_key {grant_key!r}: {what!r} isn't a parameter"]
    return []


def _thread(origin: dict[str, Any] | None) -> str | None:
    t = (origin or {}).get("thread")
    return str(t) if t else None


class Grants:
    def __init__(self, db: Database, bus: EventBus) -> None:
        self.db, self.bus = db, bus

    async def match(self, tool: ToolDef, arguments: Any, origin: dict[str, Any] | None,
                    key: str | None = None) -> dict[str, Any] | None:
        """The newest live grant that covers this call, or None. Counts the use. `key`: the mod's own (27.4)."""
        key, thread = key or key_of(tool.grant_key, arguments), _thread(origin)
        rows = await self.db.fetchall(
            "SELECT * FROM grants WHERE (expires_ts IS NULL OR expires_ts > ?) AND (scope = 'always' OR thread = ?) "
            "ORDER BY created_ts DESC", (time.time(), thread or "\0"))
        for r in rows:
            if fnmatch.fnmatchcase(tool.name, r["tool"]) and (r["key"] is None or r["key"] == key):
                await self.db.execute("UPDATE grants SET used = used + 1, last_used_ts = ? WHERE id = ?", (time.time(), r["id"]))
                return r
        return None

    def check(self, tool: ToolDef, arguments: Any, origin: dict[str, Any] | None, remember: str,
              confirm: bool, limits: dict[str, Any] | None = None) -> dict[str, Any] | None:
        """What `remember` would write for an approved call (None for `once`); raises HubError when it can't."""
        from utils.server import HubError

        if remember not in REMEMBER:
            raise HubError(422, "invalid_arguments", f"remember must be one of {', '.join(REMEMBER)}")
        if remember == "once":
            return None
        if limits and limits.get("once"):
            raise HubError(422, "once_only", f"{tool.name}: this kind of call ({limits.get('action')}) asks every time",
                           {"fix": "allow it once"})
        thread = _thread(origin)
        if remember == "thread" and thread is None:
            raise HubError(422, "no_thread", "this call isn't from a chat, so it can't be allowed in this chat",
                           {"fix": "allow it once, or always"})
        if remember == "always" and tool.risk in CONFIRM_RISKS and not confirm:
            raise HubError(422, "confirm_needed", f"always allowing a {tool.risk} tool needs a second confirm",
                           {"fix": "confirm on the card (confirm: true), or allow it once or in this chat"})
        key = (limits or {}).get("key") or key_of(tool.grant_key, arguments)
        if tool.grant_key and key is None:
            raise HubError(422, "no_grant_key", f"{tool.name} has no {tool.grant_key} in these arguments to remember",
                           {"fix": "allow it once"})
        return {"tool": tool.name, "key": key, "kind": tool.grant_key, "risk": tool.risk, "scope": remember,
                "thread": thread if remember == "thread" else None}

    async def add(self, tool: str, key: str | None, scope: str, thread: str | None = None, *, kind: str | None = None,
                  risk: str | None = None, expires_ts: float | None = None, note: str = "") -> dict[str, Any]:
        gid = "gr_" + secrets.token_hex(6)
        await self.db.execute(
            "INSERT INTO grants (id, tool, key, kind, risk, scope, thread, created_ts, expires_ts, note) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (gid, tool, key, kind, risk, scope, thread, time.time(), expires_ts, note))
        g = await self.get(gid)
        self.bus.publish({"type": "grant", "grant": g})
        return g  # type: ignore[return-value]

    async def get(self, gid: str) -> dict[str, Any] | None:
        return await self.db.fetchone("SELECT * FROM grants WHERE id = ?", (gid,))

    async def list(self, thread: str | None = None, tool: str | None = None) -> list[dict[str, Any]]:
        """Live grants, newest first; expired ones are removed."""
        await self.db.execute("DELETE FROM grants WHERE expires_ts IS NOT NULL AND expires_ts <= ?", (time.time(),))
        sql, args = "SELECT * FROM grants WHERE 1 = 1", []
        if thread:
            sql, args = sql + " AND thread = ?", [*args, thread]
        if tool:
            sql, args = sql + " AND tool = ?", [*args, tool]
        return await self.db.fetchall(sql + " ORDER BY created_ts DESC", args)

    async def revoke(self, gid: str) -> bool:
        n = await self.db.execute("DELETE FROM grants WHERE id = ?", (gid,))
        if n:
            self.bus.publish({"type": "grant_deleted", "id": gid})
        return bool(n)

    async def end_thread(self, thread: str) -> int:
        """A chat was deleted: its `thread` grants go with it."""
        ids = [r["id"] for r in await self.db.fetchall("SELECT id FROM grants WHERE thread = ?", (thread,))]
        for gid in ids:
            await self.revoke(gid)
        return len(ids)
