"""Permissions, chat modes and approvals (plan 13.2, 25.1, 27.4).

**Modes** (after Claude Code's): `plan` (read and explain; nothing changes), `manual` (everything
that changes something asks), `accept_edits` (edits apply, commands ask), `auto` (edits apply, a
judge decides commands: until plan Phase 30 builds it, they ask) and `bypass` (edits and commands
in the sandbox run; only folders that allow it). The old names map over: `ask` → `manual`,
`read_only` → `plan`; `auto` is now the Auto mode, which behaves as `accept_edits` did as "Use
defaults" for every tool without limits.

**Deciding a call** follows one fixed order (architecture §14.7); the first that answers wins:

1. the **deny** list of `config.toml [agent.permissions]` (name globs);
2. a **mod's limits** (a workspace folder, plan 27): the mod's preflight (`[agent] limits`) says
   what the call would do (`action`), the folder's level and Bypass, and refuses what a hard limit
   or the level stops. Nothing below lifts a refusal; the mod checks again when the call arrives.
   A preflight's `ask_folder` (a read in a folder the chat doesn't have, plan 34) asks, in every mode;
3. the chat's **mode**: for a call with limits, the cell of `CELLS` for its action (run, ask,
   refuse, or the judge); without limits, `plan` denies everything but `read`;
4. a **grant** that covers the call allows it (never for `once` actions: host runs, commits,
   anything touching a remote);
5. the **ask** list; then a **page the chat's search found** (a `web_fetch` of a URL that a `web_search`
   in the same chat returned, `utils/tools/searched.py`), or of a **link the user typed** in the chat, runs; then
   the **allow** list (`execute`
   ignores the allow list: only a grant skips its card);
6. the **risk default**: `read` runs; in `accept_edits`, `auto` and `bypass` `write` and `generate`
   run; everything else asks (`network`, `execute` and `destructive` in every mode).

One exception sits between 3 and 4: a tool in `ASK_AFTER_UNTRUSTED` (a lasting preference, which goes
into every later chat's prompt) asks when the call's origin says its chat has read untrusted text
(`origin.untrusted`: a page, a file, a transcript), whatever a grant, the allow list or the mode says.

**The judge** (plan Phase 30): a cell (or, in Auto, a `network` tool without limits) may answer
`"judge"`. `decide` stays pure; the caller then awaits `judge()`, which Phase 30 replaces. Until
then it fails closed: "ask".

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

MODES = ("plan", "manual", "accept_edits", "auto", "bypass")
OLD_MODES = {"ask": "manual", "read_only": "plan"}
MODE_WORD = {"plan": "Plan", "manual": "Manual", "accept_edits": "Accept edits", "auto": "Auto", "bypass": "Bypass"}
EDITS_RUN = ("accept_edits", "auto", "bypass")    # modes where `write` and `generate` tools run without a card
AUTO_RUNS = ("write", "generate")
ACTIONS = ("read", "edit", "delete", "commit", "command", "network", "host", "remote", "change")
ASK_AFTER_UNTRUSTED = ("hub_set_preference", "agent_memory_save", "agent_memory_entity")   # never saved unseen by a chat that read a page, file or transcript

# The mode × action table (plan Phase 27). "judge": Auto's judge decides (Phase 30); until then it asks.
# `change` (calendar 4.1): a change to your own records (a calendar item) that runs only when you asked for it: it
# asks in Manual and Accept edits (which accepts file edits), and the judge reads your words in Auto.
CELLS: dict[str, dict[str, str]] = {
    "plan":         {"read": "allow", "edit": "deny", "delete": "deny", "commit": "deny", "command": "deny",
                     "network": "deny", "host": "deny", "remote": "deny", "change": "deny"},
    "manual":       {"read": "allow", "edit": "ask", "delete": "ask", "commit": "ask", "command": "ask",
                     "network": "ask", "host": "ask", "remote": "ask", "change": "ask"},
    "accept_edits": {"read": "allow", "edit": "allow", "delete": "ask", "commit": "ask", "command": "ask",
                     "network": "ask", "host": "ask", "remote": "ask", "change": "ask"},
    "auto":         {"read": "allow", "edit": "allow", "delete": "judge", "commit": "ask", "command": "judge",
                     "network": "judge", "host": "ask", "remote": "ask", "change": "judge"},
    "bypass":       {"read": "allow", "edit": "allow", "delete": "allow", "commit": "allow", "command": "allow",
                     "network": "allow", "host": "ask", "remote": "ask", "change": "allow"},
}
ACTION_WORD = {"read": "reads", "edit": "edits", "delete": "deletes", "commit": "commits", "command": "commands",
               "network": "commands with internet", "host": "commands on your machine", "remote": "git remotes",
               "change": "changes to your records"}


def canonical(mode: str | None) -> str:
    """A mode by its new or old name; unknown → manual."""
    m = OLD_MODES.get(mode or "", mode or "")
    return m if m in MODES else "manual"


def decide(name: str, risk: str, config: Config, mode: str = "manual",
           grant: dict[str, Any] | None = None, limits: dict[str, Any] | None = None,
           untrusted: bool = False, searched: bool = False, shared: bool = False) -> tuple[str, str]:
    """("allow" | "ask" | "deny" | "judge", why) for one call.

    `grant`: a grant that covers it (25.2). `limits`: the mod's preflight (27.4), or None. `untrusted`: the
    calling chat has read text from a page, a file or a transcript (the origin's `untrusted`). `searched`: a
    web_fetch of a URL the chat's own web_search returned (`utils/tools/searched.py`); `shared`: of a link the user typed
    in the chat (`searched.shared`)."""
    p = config.agent.permissions
    mode = canonical(mode)
    if any(fnmatch.fnmatchcase(name, g) for g in p.deny):
        return "deny", "denied by your permissions (Settings → Permissions)"
    if limits is not None:
        return _with_limits(name, risk, p, mode, grant, limits)
    if mode == "plan" and risk != "read":
        return "deny", "Plan mode: only tools that read can run"
    if untrusted and name in ASK_AFTER_UNTRUSTED:
        return "ask", "this chat has read a page, a file or a transcript: a lasting preference asks first"
    if grant is not None:
        return "allow", _granted(grant)
    if any(fnmatch.fnmatchcase(name, g) for g in p.ask):
        return "ask", "your permissions ask for this tool"
    if (searched or shared) and risk in ("read", "network"):
        return "allow", "a page your search found" if searched else "a link you shared"
    if risk != "execute" and any(fnmatch.fnmatchcase(name, g) for g in p.allow):
        return "allow", "allowed by your permissions"
    if risk == "read":
        return "allow", "reads only"
    if mode in EDITS_RUN and risk in AUTO_RUNS:
        return "allow", f"{MODE_WORD[mode]}: runs without asking"
    if mode == "auto" and risk == "network":
        return "judge", "Auto: the judge decides"
    return "ask", f"{risk} tools ask first"


def _with_limits(name: str, risk: str, p: Any, mode: str, grant: dict[str, Any] | None,
                 limits: dict[str, Any]) -> tuple[str, str]:
    refuse = limits.get("refuse")
    if refuse:
        return "deny", str(refuse.get("detail") or "the mod refused it")
    if ask := limits.get("ask_folder"):        # plan 34: a folder outside the chat's environment asks, in every mode
        return "ask", f"{ask.get('path')} isn't one of this chat's folders: it asks to read it"
    action = limits.get("action") if limits.get("action") in ACTIONS else "command"
    note = ""
    if mode == "bypass" and not limits.get("allow_bypass"):
        mode, note = "accept_edits", " (Bypass isn't allowed in this folder, so as in Accept edits)"
    cell = CELLS[mode][action]
    if cell == "deny":
        return "deny", f"{MODE_WORD[mode]} mode: {ACTION_WORD[action]} are refused{note}"
    asked = any(fnmatch.fnmatchcase(name, g) for g in p.ask)
    if cell == "allow":
        if asked:
            return "ask", "your permissions ask for this tool"
        return "allow", f"{MODE_WORD[mode]}: {ACTION_WORD[action]} run without asking{note}"
    if limits.get("once"):          # no grant covers it (a compound command, a host run, a git remote, a commit)
        if cell == "judge" and not asked:   # but Auto's judge reads each part of a compound command (judge_commands)
            return "judge", f"Auto: the judge decides{note}"
        return "ask", f"{ACTION_WORD[action]} ask every time{note}"
    if grant is not None:
        return "allow", _granted(grant)
    if asked:
        return "ask", "your permissions ask for this tool"
    if risk != "execute" and any(fnmatch.fnmatchcase(name, g) for g in p.allow):
        return "allow", "allowed by your permissions"
    if cell == "judge":
        return "judge", f"Auto: the judge decides{note}"
    return "ask", f"{MODE_WORD[mode]}: {ACTION_WORD[action]} ask first{note}"


def _granted(grant: dict[str, Any]) -> str:
    key = grant.get("key")
    what = "every site" if grant.get("kind") == "url:any" and key == "*" else key   # web-approvals 2.1
    return ("allowed in this chat" if grant.get("scope") == "thread" else "always allowed") + (f" for {what}" if what else "")


async def judge(hub: Any, tool: Any, arguments: dict[str, Any], origin: dict[str, Any] | None,
                limits: dict[str, Any] | None, why: str) -> tuple[str, str, dict[str, Any]]:
    """Auto mode's judge (plan 30.3, `utils/tools/judge.py`): ("allow" | "ask", why, record). Never "deny"; fails
    closed (anything unexpected asks)."""
    from utils.tools.judge import judge_call

    try:
        steps = None
        if getattr(hub.config.agent.judge, "context", "none") != "none" and getattr(hub, "db", None) is not None:
            from utils.tools.judge_context import load
            steps = await load(hub.db, origin)     # the turn so far, from tool_calls: never stored with the call
        j = await judge_call(hub.config, tool.name, arguments, origin, limits, steps)
    except Exception as e:  # noqa: BLE001: the judge never breaks a call; it asks
        return "ask", f"Auto: asked you (the judge failed: {type(e).__name__})", {"verdict": "ask", "source": "fail-closed"}
    verdict = "allow" if j.verdict == "allow" else "ask"
    record = {"verdict": verdict, "reason": j.reason, "source": j.source, "rule": j.rule, "ms": j.ms, "model": j.model,
              "summary": j.detail.get("summary", "")}
    return verdict, (f"Auto: ran (judged safe: {j.reason})" if verdict == "allow" else f"Auto: asked you ({j.reason})"), record


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

    def expired(self, a: dict[str, Any]) -> bool:
        """A pending approval past `agent.approval_ttl_h` (whether or not a listing has closed it yet)."""
        return a.get("state") == "pending" and float(a.get("created_ts") or 0) < time.time() - self.config.agent.approval_ttl_h * 3600

    async def expire(self) -> int:
        cutoff = time.time() - self.config.agent.approval_ttl_h * 3600
        rows = await self.db.fetchall("SELECT id FROM approvals WHERE state = 'pending' AND created_ts < ?", (cutoff,))
        for r in rows:
            await self.close(r["id"], "expired", reason="not decided in time")
        return len(rows)
