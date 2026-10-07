"""Permissions and approvals (plan 13.2).

**Permissions:** `config.toml [agent.permissions]` holds `deny`, `ask` and `allow` lists of name
globs, checked deny → ask → allow; then the default by risk (`read` runs, everything else asks).
A call's **mode** narrows it further: `ask` (the default), `auto` (only `destructive` asks) or
`read_only` (only `read` runs).

**Approvals:** a call that has to ask is stored in `approvals` and runs nothing. Deciding it
(`POST /api/approvals/{id}`) may carry edited arguments: those are validated and are what runs.
Approvals outlive restarts; undecided ones expire after `agent.approval_ttl_h` hours.
"""

from __future__ import annotations

import fnmatch
import json
import secrets
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from utils.config import Config
    from utils.db import Database
    from utils.events import EventBus

MODES = ("ask", "auto", "read_only")


def decide(name: str, risk: str, config: Config, mode: str = "ask") -> tuple[str, str]:
    """("allow" | "ask" | "deny", why) for one call."""
    p = config.agent.permissions
    if any(fnmatch.fnmatchcase(name, g) for g in p.deny):
        return "deny", "denied by your permissions (Settings → Agent)"
    if mode == "read_only" and risk != "read":
        return "deny", "the thread is read-only: only tools that read can run"
    if any(fnmatch.fnmatchcase(name, g) for g in p.ask):
        return "ask", "your permissions ask for this tool"
    if any(fnmatch.fnmatchcase(name, g) for g in p.allow):
        return "allow", "allowed by your permissions"
    if risk == "read":
        return "allow", "reads only"
    if mode == "auto" and risk != "destructive":
        return "allow", "Use defaults: runs without asking"
    return "ask", f"{risk} tools ask first"


def _row(r: dict[str, Any] | None) -> dict[str, Any] | None:
    if r is None:
        return None
    out = dict(r)
    for k in ("arguments", "final", "ask_fields", "origin"):
        if out.get(k) is not None:
            out[k] = json.loads(out[k])
    return out


class Approvals:
    def __init__(self, db: Database, bus: EventBus, config: Config) -> None:
        self.db, self.bus, self.config = db, bus, config

    async def create(self, tool: str, arguments: dict[str, Any], ask_fields: list[str], risk: str,
                     origin: dict[str, Any]) -> dict[str, Any]:
        aid = "ap_" + secrets.token_hex(6)
        now = time.time()
        await self.db.execute(
            "INSERT INTO approvals (id, tool, arguments, ask_fields, risk, origin, state, created_ts) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)",
            (aid, tool, json.dumps(arguments), json.dumps(ask_fields), risk, json.dumps(origin), now))
        a = await self.get(aid)
        self.bus.publish({"type": "approval", "approval": a})
        return a  # type: ignore[return-value]

    async def get(self, aid: str) -> dict[str, Any] | None:
        return _row(await self.db.fetchone("SELECT * FROM approvals WHERE id = ?", (aid,)))

    async def list(self, state: str | None = "pending", limit: int = 100) -> list[dict[str, Any]]:
        await self.expire()
        if state:
            rows = await self.db.fetchall("SELECT * FROM approvals WHERE state = ? ORDER BY created_ts DESC LIMIT ?", (state, limit))
        else:
            rows = await self.db.fetchall("SELECT * FROM approvals ORDER BY created_ts DESC LIMIT ?", (limit,))
        return [_row(r) for r in rows]  # type: ignore[misc]

    async def close(self, aid: str, state: str, final: dict[str, Any] | None = None, reason: str | None = None,
                    call_id: str | None = None) -> bool:
        """Pending → state, once. False when it was already decided."""
        n = await self.db.execute(
            "UPDATE approvals SET state = ?, final = ?, reason = ?, call_id = ?, decided_ts = ? WHERE id = ? AND state = 'pending'",
            (state, json.dumps(final) if final is not None else None, reason, call_id, time.time(), aid))
        if n:
            self.bus.publish({"type": "approval", "approval": await self.get(aid)})
        return bool(n)

    async def set_call(self, aid: str, call_id: str) -> None:
        await self.db.execute("UPDATE approvals SET call_id = ? WHERE id = ?", (call_id, aid))

    async def expire(self) -> int:
        cutoff = time.time() - self.config.agent.approval_ttl_h * 3600
        rows = await self.db.fetchall("SELECT id FROM approvals WHERE state = 'pending' AND created_ts < ?", (cutoff,))
        for r in rows:
            await self.close(r["id"], "expired", reason="not decided in time")
        return len(rows)
