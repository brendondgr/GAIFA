"""Permissions and approvals (plan 13.2, 25.1).

**Deciding a call** follows one fixed order (architecture §14), the first that answers wins:

1. the **deny** list of `config.toml [agent.permissions]` (name globs);
2. the thread's **mode**: `read_only` denies everything but `read`;
3. a **mod's own limits** (a workspace folder's level, Phase 27): the mod enforces them when the
   call reaches it, so no grant, list entry or approval lifts them;
4. a **grant** that covers the call (plan 25.2, `utils/tools/grants.py`) allows it;
5. the **ask**, then **allow** list (`execute` ignores the allow list: only a grant skips its card);
6. the **risk default**: `read` runs; in `auto` mode `write` and `generate` run; everything else
   asks (`network`, `execute` and `destructive` ask in every mode).

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


AUTO_RUNS = ("write", "generate")   # what `auto` mode runs without a card


def decide(name: str, risk: str, config: Config, mode: str = "ask",
           grant: dict[str, Any] | None = None) -> tuple[str, str]:
    """("allow" | "ask" | "deny", why) for one call. `grant`: a grant that covers it (25.2)."""
    p = config.agent.permissions
    if any(fnmatch.fnmatchcase(name, g) for g in p.deny):
        return "deny", "denied by your permissions (Settings → Agent)"
    if mode == "read_only" and risk != "read":
        return "deny", "the thread is read-only: only tools that read can run"
    if grant is not None:
        return "allow", ("allowed in this chat" if grant.get("scope") == "thread" else "always allowed") + \
            (f" for {grant['key']}" if grant.get("key") else "")
    if any(fnmatch.fnmatchcase(name, g) for g in p.ask):
        return "ask", "your permissions ask for this tool"
    if risk != "execute" and any(fnmatch.fnmatchcase(name, g) for g in p.allow):
        return "allow", "allowed by your permissions"
    if risk == "read":
        return "allow", "reads only"
    if mode == "auto" and risk in AUTO_RUNS:
        return "allow", "Use defaults: runs without asking"
    return "ask", f"{risk} tools ask first"


def _row(r: dict[str, Any] | None) -> dict[str, Any] | None:
    if r is None:
        return None
    out = dict(r)
    for k in ("arguments", "final", "ask_fields", "origin", "filled", "edited"):
        if out.get(k) is not None:
            out[k] = json.loads(out[k])
    return out


class Approvals:
    def __init__(self, db: Database, bus: EventBus, config: Config) -> None:
        self.db, self.bus, self.config = db, bus, config

    async def create(self, tool: str, arguments: dict[str, Any], ask_fields: list[str], risk: str,
                     origin: dict[str, Any], filled: dict[str, str] | None = None) -> dict[str, Any]:
        aid = "ap_" + secrets.token_hex(6)
        now = time.time()
        await self.db.execute(
            "INSERT INTO approvals (id, tool, arguments, ask_fields, risk, origin, state, created_ts, filled) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)",
            (aid, tool, json.dumps(arguments), json.dumps(ask_fields), risk, json.dumps(origin), now, json.dumps(filled) if filled else None))
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
                    call_id: str | None = None, edited: list[str] | None = None) -> bool:
        """Pending → state, once. False when it was already decided. `edited`: the fields the user changed (21.1)."""
        n = await self.db.execute(
            "UPDATE approvals SET state = ?, final = ?, reason = ?, call_id = ?, decided_ts = ?, edited = ? WHERE id = ? AND state = 'pending'",
            (state, json.dumps(final) if final is not None else None, reason, call_id, time.time(),
             json.dumps(edited) if edited is not None else None, aid))
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
