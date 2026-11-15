"""Can this mod be used, and if not, why and what turns it on (plan capability-enablement 1.2).

One answer read by every caller: `GET /api/services` (`availability`), the tool catalog, the agent's prompt, the
doctor and the UI. `status`:

    on              ready, degraded or starting
    starts_on_use   stopped (or stopping), set up and turned on: a call to its tools starts it
    off             turned off (`[services.<id>] enabled = false`)
    not_set_up      its command isn't there (no venv, binary or script): `gaifa setup <id>` never ran
    cant_run        its recorded variant needs hardware this machine doesn't have
    failed          its process failed (or its last start did), or an external mod that doesn't answer
    broken          its service.toml has errors

`fix` is `{kind, id, command, tool}`: `kind` setup | enable | start | logs | none, `command` what a person runs, `tool`
the hub tool that does it ("" until that tool exists: `hub_enable_service` with step 1.7, `hub_setup` with 4.1).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from utils.services import Service, ServiceManager

Status = Literal["on", "starts_on_use", "off", "not_set_up", "cant_run", "failed", "broken"]
USABLE = ("on", "starts_on_use")
# the hub tool for each kind of fix, once it exists in the catalog
FIX_TOOLS: dict[str, str] = {"start": "hub_start_service"}


def _fix(kind: str, sid: str, command: str = "") -> dict[str, str]:
    return {"kind": kind, "id": sid, "command": command, "tool": FIX_TOOLS.get(kind, "")}


def _first_line(text: str | None) -> str:
    return (text or "").split("\n\nLast log lines:")[0].strip().splitlines()[0][:200] if (text or "").strip() else ""


def availability(mgr: ServiceManager, svc: Service) -> dict[str, Any]:
    """`{status, why, fix}` for one mod; `why` is a sentence for a person ("Web isn't set up on this machine")."""
    name, sid = svc.mod.name, svc.id
    if svc.errors:
        return {"status": "broken", "why": f"{name} has a problem in its service.toml: {svc.errors[0]}",
                "fix": _fix("none", sid, f"gaifa check {sid}")}
    if not mgr.installed(svc):
        return {"status": "not_set_up", "why": f"{name} isn't set up on this machine", "fix": _fix("setup", sid, f"gaifa setup {sid}")}
    why = mgr.unavailable(svc)
    if why:
        return {"status": "cant_run", "why": f"{name} can't run on this machine: {why}", "fix": _fix("setup", sid, f"gaifa setup {sid}")}
    if not svc.eff.enabled:
        return {"status": "off", "why": f"{name} is turned off", "fix": _fix("enable", sid, f"turn {name} on in Settings → Services")}
    if svc.state in ("ready", "degraded", "starting"):
        return {"status": "on", "why": "", "fix": _fix("none", sid)}
    if svc.external:
        return {"status": "failed", "why": f"{name} doesn't answer (it runs outside GAIFA)", "fix": _fix("none", sid)}
    if svc.state == "failed":
        err = _first_line(svc.last_error)
        return {"status": "failed", "why": f"{name} didn't start" + (f": {err}" if err else ""), "fix": _fix("logs", sid, f"gaifa logs {sid}")}
    return {"status": "starts_on_use", "why": f"{name} is stopped; using it starts it", "fix": _fix("start", sid, f"gaifa start {sid}")}
