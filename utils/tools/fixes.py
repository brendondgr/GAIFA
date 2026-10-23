"""Fix-it hints on a failed tool call (plan 46.5): what to do about the error, as buttons the chat shows and steps
the agent may take, and the mod's log lines around the failure.

    error["fixes"] = [{"label": "Start Images & Video", "tool": "hub_start_service", "arguments": {"id": "comfy"}},
                      {"label": "Restart Images & Video", "service": "comfy", "action": "restart"},
                      {"label": "Retry with the fast preset", "retry": {"preset": "fast"}},
                      {"label": "Retry", "retry": {}}]
    error["log"] = ["… the lines that name the error …"]

A `tool` fix is a hub tool call; a `service` fix is a hub route (the chat calls it; the agent can't); `retry` runs the
same call again with those arguments changed. Never fixes for a call refused before it ran (bad arguments, an
unknown tool, a denial): the agent fixes those itself.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from utils.server import Hub
    from utils.tools.catalog import ToolDef

OOM = re.compile(r"out of memory|\bOOM\b|MemoryError|cannot allocate|Killed\b|hipErrorOutOfMemory|CUDA error: out of memory", re.I)
NOTABLE = re.compile(r"error|exception|traceback|failed|fatal|killed|out of memory|refused|timed? ?out", re.I)
NO_FIX = {"invalid_arguments", "unknown_tool", "unknown_call", "denied", "unknown_output", "invalid_pref", "job_timeout"}
LIGHT = ("fast", "draft", "low", "quick", "turbo")


def lighter_preset(tool: ToolDef, current: Any) -> str | None:
    """The tool's lightest preset other than the one it ran with, by name (fast, draft, …)."""
    enum = ((tool.parameters or {}).get("properties", {}).get("preset") or {}).get("enum") or []
    for word in LIGHT:
        for v in enum:
            if isinstance(v, str) and word in v.lower() and v != current:
                return v
    return None


def log_excerpt(lines: list[dict[str, Any]], n: int = 8) -> list[str]:
    """The last `n` lines that name an error, with the line before each; else the last few lines."""
    texts = [str(x.get("text", "")).rstrip() for x in lines if x.get("text")]
    hits = [i for i, t in enumerate(texts) if NOTABLE.search(t)]
    if not hits:
        return [t[:300] for t in texts[-3:]]
    keep: list[int] = []
    for i in hits[-n:]:
        for j in (i - 1, i):
            if j >= 0 and j not in keep:
                keep.append(j)
    return [texts[i][:300] for i in sorted(keep)][-n:]


def fixes_for(tool: ToolDef, args: dict[str, Any], error: dict[str, Any], name: str, log: list[str]) -> list[dict[str, Any]]:
    code, mod = error.get("code"), tool.mod
    text = " ".join([str(error.get("detail", "")), *log])
    out: list[dict[str, Any]] = []
    if code in NO_FIX or code is None:
        return out
    if code == "service_not_running" and mod and mod != "hub":
        out.append({"label": f"Start {name}", "tool": "hub_start_service", "arguments": {"id": mod}})
    elif code == "needs_room":
        out.append({"label": "Free the GPU", "tool": "hub_free_gpu", "arguments": {}})
    elif code in ("mod_error", "upstream_error", "service_failed") and mod and mod != "hub":
        out.append({"label": f"Restart {name}", "service": mod, "action": "restart"})
    elif code == "tool_unavailable" and mod:
        out.append({"label": f"Set it up: aihub setup {mod}", "command": f"aihub setup {mod}"})
        return out
    if OOM.search(text):
        if not any(f.get("tool") == "hub_free_gpu" for f in out):
            out.append({"label": "Free the GPU", "tool": "hub_free_gpu", "arguments": {}})
        light = lighter_preset(tool, args.get("preset"))
        if light:
            out.append({"label": f"Retry with the {light} preset", "retry": {"preset": light}})
    out.append({"label": "Retry", "retry": {}})
    return out


async def attach(hub: Hub, tool: ToolDef, args: dict[str, Any], error: dict[str, Any]) -> None:
    """Add `fixes` and `log` to a failed call's error (in place). Never raises."""
    try:
        log: list[str] = []
        mod = tool.mod
        svc = hub.services.services.get(mod) if mod and hub.services else None
        if svc is not None and error.get("code") not in NO_FIX:
            try:
                log = log_excerpt(await hub.services.logs(mod, 60))
            except Exception:  # noqa: BLE001 - no log is fine
                log = []
        name = svc.mod.name if svc is not None else (mod or "the mod")
        fixes = fixes_for(tool, args, error, name, log)
        if fixes:
            error["fixes"] = fixes
        if log:
            error["log"] = log
    except Exception:  # noqa: BLE001 - hints never break a call
        pass
