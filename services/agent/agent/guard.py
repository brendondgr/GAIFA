"""Guards that end a stuck turn (plan 14 and capability-enablement 2.3), read from the chat's events.

- **Repeats:** the same call with the same arguments is refused from the third time; a turn whose last two refusals
  were repeats wraps up (`stuck`).
- **Out for this turn:** a mod whose tool answered `capability_unavailable`, `tool_unavailable` or `service_not_running`
  since the user's message is out for the rest of the turn: a further call to any of its tools is answered here with
  that first error, unless `hub_setup`, `hub_enable_service` or `hub_start_service` turned it on since.
- **Turned off:** a call to a mod the user turned off turns it on (`hub_enable_service`) and runs again (2.4).
- **Failing:** after `max_fails` error results in a row (any tools, any arguments) the next model call gets no tools
  and a note listing what failed, so a varied retry ends in words instead of running to the step limit.
"""

from __future__ import annotations

import json
from typing import Any, Callable

OUT_CODES = ("capability_unavailable", "tool_unavailable", "service_not_running")
TURN_ON = ("hub_setup", "hub_enable_service", "hub_start_service")
MAX_FAILS = 4
ALREADY = "you already know this isn't available in this turn: tell the user what is missing and don't call it again"


def turn(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The events since the user's last message."""
    start = max((e["seq"] for e in events if e["type"] == "user"), default=0)
    return [e for e in events if e["seq"] > start]


def turn_calls(events: list[dict[str, Any]], cid: str) -> list[str]:
    """Tool names called so far in this turn, not counting `cid`."""
    return [e["payload"]["name"] for e in turn(events) if e["type"] == "tool_call" and e["payload"].get("id") != cid]


def _key(p: dict[str, Any]) -> tuple[str, str]:
    return p["name"], json.dumps(p.get("arguments") or {}, sort_keys=True)


def repeated(events: list[dict[str, Any]], e: dict[str, Any]) -> int:
    """How many calls of this tool with these arguments in this turn, this one included."""
    key = _key(e["payload"])
    return sum(1 for x in turn(events) if x["type"] == "tool_call" and x["seq"] <= e["seq"] and _key(x["payload"]) == key)


def _codes(events: list[dict[str, Any]]) -> list[str | None]:
    return [(x["payload"].get("error") or {}).get("code") for x in turn(events) if x["type"] == "tool_result"]


def stuck(events: list[dict[str, Any]]) -> bool:
    """The turn only repeats itself: the last result was a refused repeat, and not the first one since the user spoke."""
    codes = _codes(events)
    return bool(codes) and codes[-1] == "repeated_call" and codes.count("repeated_call") >= 2


def _turned_on(p: dict[str, Any], args: dict[str, Any]) -> set[str]:
    """The mods a successful hub_setup / hub_enable_service / hub_start_service call turned on."""
    if p.get("name") not in TURN_ON or p.get("status") != "done":
        return set()
    ids = args.get("ids") if isinstance(args.get("ids"), list) else [args.get("id")]
    return {str(i) for i in ids if i}


def out_for_turn(events: list[dict[str, Any]], mod_of: Callable[[str], str | None]) -> dict[str, dict[str, Any]]:
    """{mod: its first refusal's error} for the mods refused in this turn and not turned on since; a tool the mod
    turned off itself is keyed `tool:<name>`."""
    out: dict[str, dict[str, Any]] = {}
    args: dict[str, dict[str, Any]] = {}
    for e in turn(events):
        p = e["payload"]
        if e["type"] == "tool_call":
            args[p.get("id")] = p.get("arguments") if isinstance(p.get("arguments"), dict) else {}
            continue
        if e["type"] != "tool_result":
            continue
        for m in _turned_on(p, args.get(p.get("id"), {})):
            out.pop(m, None)
        err = p.get("error") or {}
        if err.get("code") in OUT_CODES and p.get("name") not in TURN_ON:
            # a tool the mod itself turned off (off_by_mod) is out alone; its mod's other tools still work
            key = f"tool:{p['name']}" if err.get("state") == "off_by_mod" else (err.get("service") or mod_of(p["name"]))
            if key and key not in out:
                out[key] = err
    return out


def answer_out(name: str, err: dict[str, Any]) -> dict[str, Any]:
    """The local answer for a call to a mod already out for this turn: its first error, and don't call again."""
    return {"status": "error", "error": {"code": err.get("code") or "capability_unavailable",
                                         "detail": f"{name}: {err.get('detail') or 'not available'}", "fix": ALREADY,
                                         **({"service": err["service"]} if err.get("service") else {}),
                                         **({"turn_on": err["turn_on"]} if err.get("turn_on") else {})}}


def failing(events: list[dict[str, Any]], max_fails: int = MAX_FAILS) -> list[str]:
    """The last `max_fails` results when each was an error ("web_search: capability_unavailable", …), else []."""
    rows = [x["payload"] for x in turn(events) if x["type"] == "tool_result"]
    if max_fails <= 0 or len(rows) < max_fails:
        return []
    last = rows[-max_fails:]
    if any(r.get("status") == "done" or not r.get("error") for r in last):
        return []
    return [f"{r.get('name')}: {(r.get('error') or {}).get('code') or r.get('status')}" for r in last]


def wrap_note(failed: list[str]) -> str:
    """The note the model reads when the failure guard ends its tools for this reply."""
    return ("(A note from the app, not from the user: your last tool calls all failed: " + "; ".join(failed) + ". "
            "Tools are off for this reply. Answer the user in plain text: what you tried, what is missing or broken, "
            "and what they can do about it.)")


async def turn_on_and_retry(agent: Any, tid: str, name: str, args: Any, origin: dict[str, Any], mode: str,
                            res: dict[str, Any]) -> dict[str, Any]:
    """capability-enablement 2.4: a call to a mod the user turned off (set up, `enabled = false`) turns it on with
    hub_enable_service (decided like any call: allowed by default, refused in Plan) and runs once more. Only in a chat
    someone is watching; the hub still refuses such calls from every other caller."""
    err = res.get("error") or {}
    on = err.get("turn_on") or {}
    if err.get("code") != "capability_unavailable" or err.get("state") != "off" or on.get("tool") != "hub_enable_service" \
            or origin.get("unattended"):
        return res
    done = await agent.hub.call("hub_enable_service", on.get("arguments") or {}, {**origin, "for_tool": name}, mode, wait=60)
    if done.get("status") != "done":
        return res
    agent.emit(tid, "note", {"text": f"turned on {err.get('service') or (on.get('arguments') or {}).get('id')} to run {name}", "level": "info"})
    return await agent.hub.call(name, args, origin, mode, wait=2)
