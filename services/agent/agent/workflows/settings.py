"""What a sub-agent takes from its parent, and the workflow limits (plan agent-workflows 1.2).

A sub-agent gets the parent's model (unless the spawn names another), mode, project, environments, tool groups, MCP
servers, and whether anyone is watching (`unattended`); it never learns (`no_learn`) and has its own step limit
(`max_steps`). It isn't a scheduled run (`task`, `task_run` stay with the parent) and is read-only unless spawned as
the workflow's writer (`spawn.write`; the hub refuses its other calls, 1.4).

Limits come from the hub's `[agent.workflows]` (`GET /api/settings` → `workflows`), else DEFAULTS.
"""

from __future__ import annotations

import time
from typing import Any

DEFAULTS: dict[str, Any] = {
    "enabled": True,
    "parallel_local": 1,        # sub-agents at once on this machine's GPU (they only queue there)
    "parallel_remote": 3,       # …on remote and cloud models
    "max_children": 8,          # per parent turn
    "max_depth": 1,             # a sub-agent can't spawn its own
    "child_max_steps": 25,
    "workflow_tokens": 400_000,  # per parent turn, every sub-agent's prompt and reply tokens together
    "queue_wait_s": 1800,       # a queued sub-agent that waited longer is dropped
}
INHERIT = ("project", "environment", "task_env", "task_only", "disabled", "pinned", "mcp_on", "unattended", "use_profile",
           "use_project_memory", "dry_run", "window")
CACHE_S = 30


class Limits:
    """`[agent.workflows]`, read from the hub at most every CACHE_S seconds; `fixed` (tests) wins."""

    def __init__(self, hub: Any, fixed: dict[str, Any] | None = None) -> None:
        self.hub, self.fixed = hub, fixed or {}
        self._at, self._got = 0.0, dict(DEFAULTS)

    async def get(self) -> dict[str, Any]:
        if time.monotonic() - self._at > CACHE_S:
            try:
                got = (await self.hub.settings()).get("workflows") or {}
            except Exception:  # noqa: BLE001: the hub restarting: the last known
                got = None
            if got is not None:
                self._got = {**DEFAULTS, **{k: v for k, v in got.items() if k in DEFAULTS and v is not None}}
                self._at = time.monotonic()
        return {**self._got, **self.fixed}

    def forget(self) -> None:
        self._at = 0.0


def child_settings(parent: dict[str, Any], spawn: dict[str, Any], max_steps: int) -> dict[str, Any]:
    st = parent.get("settings") or {}
    out = {k: (list(st[k]) if isinstance(st[k], list) else st[k]) for k in INHERIT if k in st}
    return {**out, "no_learn": True, "max_steps": int(max_steps), "spawn": spawn}


def depth_of(thread: dict[str, Any]) -> int:
    """0 for a chat, 1 for a sub-agent, 2 for a sub-agent's…"""
    return int(((thread.get("settings") or {}).get("spawn") or {}).get("depth") or 0)
