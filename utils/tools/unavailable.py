"""Tools whose mod can't be used, answered at once (plan capability-enablement 1.5).

A call to a tool whose mod is not set up, turned off, can't run here or is broken never tries to start it: it answers
`capability_unavailable` with what is missing in words the agent passes on ("I can't search the web or read pages:
Web isn't set up on this machine") and a fix that tells it to stop and offer to turn it on. A mod whose start failed
in the last minute answers `service_not_running` at once, so three calls aren't three start timeouts.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from utils.services.availability import availability

if TYPE_CHECKING:
    from utils.services import Service
    from utils.tools.catalog import ToolDef

BLOCKED = ("not_set_up", "off", "cant_run", "broken", "off_by_mod")   # a call can't fix these by starting the mod
COOLDOWN_S = 60.0                                                       # after a failed start, calls fail at once


def turn_on(av: dict[str, Any]) -> dict[str, Any] | None:
    """The hub tool and arguments that turn the mod on (`ToolDef.turn_on`), or None when there is no tool for it yet."""
    fix = av["fix"]
    tool = fix.get("tool") or ""
    if not tool:
        return {"tool": "", "arguments": {}, "command": fix.get("command") or ""} if fix.get("command") else None
    args: dict[str, Any] = {"ids": [fix["id"]]} if tool == "hub_setup" else {"id": fix["id"]}
    return {"tool": tool, "arguments": args, "command": fix.get("command") or ""}


def _gives(svc: Service, tool: ToolDef) -> str:
    """What the mod lets the agent do, completing "I can't …"."""
    p = svc.m.agent.provides if svc.m else None
    return p or f"use {tool.name}"


def _fix_words(svc: Service, av: dict[str, Any]) -> str:
    fix, name = av["fix"], svc.mod.name
    how = f"{fix['tool']} with id {svc.id}" if fix.get("tool") and fix["tool"] != "hub_setup" else (
        f'hub_setup with ids ["{svc.id}"]' if fix.get("tool") == "hub_setup" else f"`{fix['command']}`" if fix.get("command") else "")
    if av["status"] == "off":
        offer = (f"turn it on ({how}) if the user asked for what it does" if fix.get("tool")
                 else f"ask the user to turn {name} on in Settings → Services")
    elif av["status"] in ("not_set_up", "cant_run"):
        offer = f"offer to set it up ({how}, after the user says yes)" if how else "offer to set it up"
    else:
        offer = f"say it needs fixing ({how})" if how else "say it needs fixing"
    return f"tell the user in one sentence what is missing and {offer}; don't retry and don't reach for it another way"


def capability_error(svc: Service, tool: ToolDef, av: dict[str, Any]) -> dict[str, Any]:
    """The `capability_unavailable` error for a call to `tool`, whose mod `svc` is in state `av`."""
    err: dict[str, Any] = {"code": "capability_unavailable", "detail": f"I can't {_gives(svc, tool)}: {av['why']}",
                           "fix": _fix_words(svc, av), "state": av["status"], "service": svc.id}
    on = turn_on(av)
    if on:
        err["turn_on"] = on
    err["fixes"] = card_fixes(svc, av)
    return err


def card_fixes(svc: Service, av: dict[str, Any]) -> list[dict[str, Any]]:
    """The fix-it buttons (plan 46.5) for a mod that can't be used; never Retry."""
    kind, name = av["fix"]["kind"], svc.mod.name
    if kind == "setup":
        return [{"label": f"Set up {name}", "setup": svc.id, "command": av["fix"]["command"]}]
    if kind == "enable":
        return [{"label": f"Turn on {name}", "service": svc.id, "action": "enable"}]
    return []


def recently_failed(svc: Service) -> bool:
    return bool(svc.start_failed_at and not svc.up and time.time() - svc.start_failed_at < COOLDOWN_S)


def cooldown_error(svc: Service) -> dict[str, Any]:
    first = (svc.last_error or "it failed").split("\n\nLast log lines:")[0].strip().splitlines()[0][:200]
    return {"code": "service_not_running", "detail": f"{svc.mod.name} didn't start: {first}",
            "fix": f"don't retry in this turn; tell the user (its Logs tab says why: gaifa logs {svc.id})",
            "service": svc.id, "fixes": [{"label": f"Restart {svc.mod.name}", "service": svc.id, "action": "restart"}]}


def refusal(mgr: Any, tool: ToolDef) -> dict[str, Any] | None:
    """The error a call to `tool` answers with at once, or None when it may go ahead (it may still start the mod)."""
    if not tool.mod or tool.mod == "hub" or mgr is None:
        return None
    svc = mgr.services.get(tool.mod)
    if svc is None:
        return None
    if tool.state == "off_by_mod" and tool.why:          # the mod itself said this tool is off (1.6)
        av = {"status": "off_by_mod", "why": tool.why, "fix": {"kind": "none", "id": svc.id, "command": "", "tool": ""}}
        err = capability_error(svc, tool, av)
        err["detail"] = f"{tool.name} is off right now: {tool.why}"    # only this tool: the mod's others still work
        if tool.off_fix:
            err["fix"] = tool.off_fix + "; don't retry and don't reach for it another way"
        return err
    av = availability(mgr, svc)
    if av["status"] in BLOCKED:
        return capability_error(svc, tool, av)
    if recently_failed(svc):
        return cooldown_error(svc)
    return None


async def start_for(mgr: Any, catalog: Any, tool: ToolDef) -> dict[str, Any] | None:
    """Start a set-up mod that has never run, so its tools have their schemas; the error when it doesn't start."""
    from utils.services import ServiceError

    svc = mgr.services.get(tool.mod or "") if mgr is not None else None
    if svc is None:
        return None
    try:
        await mgr.start(svc.id, wait=True)
    except ServiceError:
        pass
    if not svc.up:
        return cooldown_error(svc)
    await catalog.tools()
    return None
