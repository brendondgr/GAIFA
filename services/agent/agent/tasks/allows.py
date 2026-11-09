"""Pre-allows from a test run (plan scheduled-tasks 3.2): what you approved while watching, as entries for the task.

`suggest(agent, task, thread_id)` reads the run's approved cards: a web page becomes its site, an MCP server's tool its
server, anything else the tool; what the task already allows is left out. `merge(allow, more)` adds entries.
"""

from __future__ import annotations

import fnmatch
from typing import Any
from urllib.parse import urlsplit

from .runner import WEB_TOOL


def _host(url: Any) -> str | None:
    try:
        h = urlsplit(str(url or "")).hostname
    except ValueError:
        return None
    return h.lower().rstrip(".") if h else None


def allowed(allow: dict[str, Any], kind: str, value: str) -> bool:
    if kind == "tool":
        return any(fnmatch.fnmatchcase(value, g) for g in allow.get("tools") or [])
    if kind == "site":
        return "*" in (allow.get("sites") or []) or value in (allow.get("sites") or [])
    return value in (allow.get("mcp") or [])


async def suggest(agent: Any, task: dict[str, Any], thread_id: str) -> list[dict[str, Any]]:
    """`[{kind: tool | site | mcp, value, tool, count}]`, in the order they were approved."""
    evs = agent.store.events(thread_id, types=("approval", "decision"))
    approved = {e["payload"].get("approval_id") for e in evs if e["type"] == "decision" and e["payload"].get("approve")}
    try:
        groups = {t["name"]: t.get("group") for t in await agent.hub.index()}
    except Exception:  # noqa: BLE001
        groups = {}
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for e in evs:
        p = e["payload"]
        if e["type"] != "approval" or p.get("approval_id") not in approved:
            continue
        tool = str(p.get("tool") or "")
        group = groups.get(tool) or ""
        if tool == WEB_TOOL and _host((p.get("arguments") or {}).get("url")):
            kind, value = "site", _host(p["arguments"]["url"])
        elif group.startswith("mcp:"):
            kind, value = "mcp", group[4:]
        else:
            kind, value = "tool", tool
        if not value or allowed(task.get("allow") or {}, kind, value):  # type: ignore[arg-type]
            continue
        key = (kind, value)  # type: ignore[assignment]
        if key in out:
            out[key]["count"] += 1
        else:
            out[key] = {"kind": kind, "value": value, "tool": tool, "count": 1}
    return list(out.values())


def merge(allow: dict[str, Any], more: dict[str, Any]) -> dict[str, list[str]]:
    out = {k: list(allow.get(k) or []) for k in ("tools", "sites", "mcp")}
    for k in out:
        for v in more.get(k) or []:
            if v not in out[k]:
                out[k].append(v)
    return out
