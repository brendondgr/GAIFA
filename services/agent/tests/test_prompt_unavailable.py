"""capability-enablement 2.1: the model knows every tool and calls only those that can run. Tools whose mod is on or
starts on use get schemas; the rest are listed under "Off on this machine" with what they give, their names, why and
the one tool that turns them on; find_tools and load_tools say so; a chat with everything on has no such section."""

from __future__ import annotations

from agent import prompts

from .test_environments import system_prompt


def tool(name, mod, state, why=None, turn_on=None, core=True):
    return {"name": name, "mod": mod, "risk": "network", "core": core, "summary": f"{name} does it", "description": f"{name} does it",
            "parameters": {"type": "object", "properties": {}}, "available": state == "on", "state": state,
            **({"why": why} if why else {}), **({"turn_on": turn_on} if turn_on else {})}


OFF_TOOLS = [
    tool("web_search", "web", "not_set_up", "Web isn't set up on this machine", {"tool": "", "arguments": {}, "command": "gaifa setup web"}),
    tool("web_fetch", "web", "not_set_up", "Web isn't set up on this machine", {"tool": "", "arguments": {}, "command": "gaifa setup web"}),
    tool("calendar_agenda", "calendar", "off", "Calendar is turned off",
         {"tool": "hub_enable_service", "arguments": {"id": "calendar"}, "command": "turn Calendar on in Settings → Services"}),
    tool("stt_transcribe", "stt", "starts_on_use", "Speech to Text is stopped; a call starts it first",
         {"tool": "hub_start_service", "arguments": {"id": "stt"}, "command": "gaifa start stt"}),
    tool("dud_go", "dud", "failed", "Dud didn't start: exited", {"tool": "", "arguments": {}, "command": "gaifa logs dud"}),
    tool("lens_find", "lens", "off_by_mod", "no SearXNG answers at http://127.0.0.1:8080"),
]
SERVICES = [
    {"id": "web", "name": "Web", "state": "stopped", "provides": "search the web and read pages",
     "availability": {"status": "not_set_up", "why": "Web isn't set up on this machine", "fix": {}}},
    {"id": "calendar", "name": "Calendar", "state": "stopped", "provides": "keep your calendar, to-dos and reminders",
     "availability": {"status": "off", "why": "Calendar is turned off", "fix": {}}},
    {"id": "stt", "name": "Speech to Text", "state": "stopped", "availability": {"status": "starts_on_use"}},
    {"id": "dud", "name": "Dud", "state": "failed", "provides": "do dud things", "availability": {"status": "failed"}},
]


def test_the_section_from_an_index():
    text = prompts.off_section([t for t in OFF_TOOLS if t["state"] != "starts_on_use"], SERVICES)
    lines = text.split("\n")
    assert "- search the web and read pages (web: web_search, web_fetch): not set up. Turn on: the user runs `gaifa setup web` (offer it)." in lines
    assert '- keep your calendar, to-dos and reminders (calendar: calendar_agenda): turned off in Settings. Turn on: hub_enable_service {"id": "calendar"}.' in lines
    assert any(ln.startswith("- do dud things (dud: dud_go): failed to start: Dud didn't start: exited.") for ln in lines)
    assert "- lens_find (lens): off right now: no SearXNG answers at http://127.0.0.1:8080." in lines
    assert prompts.off_section([], SERVICES) == ""


def test_setup_tool_waits_for_a_yes():
    on = {"tool": "hub_setup", "arguments": {"ids": ["web"]}, "command": "gaifa setup web"}
    assert prompts.turn_on_text("not_set_up", on) == ' Turn on: hub_setup {"ids": ["web"]}, after the user says yes.'


async def test_schemas_only_for_tools_that_can_run_and_the_prompt(env):
    for t in OFF_TOOLS:
        env.hub.tools[t["name"]] = t
    env.hub.more_services = SERVICES
    tid = await env.thread()
    env.model.queue({"text": "ok"})
    await env.send(tid, "what's the weather?")
    req = env.model.received[-1]
    offered = {f["function"]["name"] for f in req.get("tools") or []}
    assert "stt_transcribe" in offered                                  # stopped: still callable, the call starts it
    assert not offered & {"web_search", "web_fetch", "calendar_agenda", "dud_go", "lens_find"}
    sp = system_prompt(env)
    assert "## Off on this machine" in sp
    assert "search the web and read pages (web: web_search, web_fetch): not set up" in sp
    assert "web (not set up)" in sp and "calendar (turned off)" in sp and "stt (stopped)" in sp


async def test_no_section_when_everything_is_on(env):
    tid = await env.thread()
    env.model.queue({"text": "ok"})
    await env.send(tid, "hi")
    assert "## Off on this machine" not in system_prompt(env)


async def test_find_and_load_say_why(env):
    for t in OFF_TOOLS:
        env.hub.tools[t["name"]] = {**t, "core": False}
    tid = await env.thread()
    env.model.queue({"tool_calls": [{"name": "find_tools", "arguments": {"query": "web_search"}}]},
                    {"tool_calls": [{"name": "load_tools", "arguments": {"names": ["web_search"]}}]},
                    {"text": "Web isn't set up."})
    await env.send(tid, "search the web")
    results = [e["payload"] for e in env.events(tid) if e["type"] == "tool_result"]
    found = results[0]["content"]
    assert '"available": false' in found and "gaifa setup web" in found and "don't reach for it another way" in found
    loaded = results[1]["content"]
    assert '"not_available"' in loaded and "Web isn't set up on this machine" in loaded and '"unknown"' not in loaded
