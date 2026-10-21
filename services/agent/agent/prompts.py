"""The system prompt (plan 14.7 order): base rules, AGENT.md, the memory index, skills, the
deferred tool index, the environment, and the thread's outputs table."""

from __future__ import annotations

import time
from typing import Any

def base_text() -> str:
    """The base harness's always-on prompt (plan 22.1: services/agent/harness/systemprompt.md)."""
    from .harness import BASE_DIR
    return (BASE_DIR / "systemprompt.md").read_text().rstrip("\n")


def section(title: str, body: str) -> str:
    return f"\n\n## {title}\n{body.strip()}" if body and body.strip() else ""


def tool_index(index: list[dict[str, Any]], loaded: set[str], disabled: set[str]) -> str:
    groups: dict[str, list[dict[str, Any]]] = {}
    for t in index:
        if t["name"] in loaded or t["mod"] in disabled:
            continue
        groups.setdefault(t["mod"], []).append(t)
    lines = []
    for mod, tools in groups.items():
        names = ", ".join(f"{t['name']}" + ("" if t.get("available", True) else " (starts on use)") for t in tools)
        lines.append(f"- {mod}: {names}")
    return "\n".join(lines)


def outputs_table(outputs: list[dict[str, Any]]) -> str:
    rows = []
    for o in outputs[-40:]:
        summary = (o.get("summary") or o.get("title") or "")[:90]
        rows.append(f"#{o['n']} {o['kind']} via {o.get('tool') or '?'}: {summary} → output:{o['output_id']}")
    return "\n".join(rows)


def environment(services: list[dict[str, Any]] | None, memory: dict[str, Any] | None, model: str, window: int | None,
                vision: bool | None) -> str:
    lines = [f"Date: {time.strftime('%A %Y-%m-%d %H:%M')}", f"Model: {model}" + (f" ({window:,} token window)" if window else "")
             + (", can see images" if vision else ", can't see images (view_output returns the image's details as text)" if vision is False else "")]
    if services:
        lines.append("Mods: " + ", ".join(f"{s['id']} ({s['state']}{', loaded' if s.get('load') == 'loaded' else ''})" for s in services))
    if memory:
        lines.append(f"Memory: {memory.get('available_bytes', 0) / 1e9:.0f} GB free of {memory.get('total_bytes', 0) / 1e9:.0f} GB")
    return "\n".join(lines)


def build(parts: dict[str, str]) -> str:
    """`parts` in plan order; empty parts are left out. Returns the full system prompt. `parts["base"]`
    is the harness's systemprompt.md and `parts["guardrails"]` its guardrails.md (plan 22.1)."""
    out = (parts.get("base") or base_text()).rstrip("\n")
    out += section("Guardrails", parts.get("guardrails", ""))
    out += section("Standing instructions (AGENT.md)", parts.get("agent_md", ""))
    out += section("Memory (what you know about the user; topic files via read_skill('memory:<topic>'))", parts.get("memory", ""))
    out += section("Skills (read one with read_skill before doing that kind of task)", parts.get("skills", ""))
    out += section("More tools (not loaded; load_tools or find_tools first)", parts.get("tools", ""))
    out += section("Environment", parts.get("env", ""))
    out += section("Outputs in this chat (reference them as output:<id>)", parts.get("outputs", ""))
    out += section("Earlier in this chat (summary)", parts.get("summary", ""))
    return out


SUMMARY_PROMPT = """Summarize the conversation so far for your own later use, so the chat can continue without the full history. Keep: the user's goals and preferences, decisions made, every output reference (#n and output:<id>) with what it is, open questions, the current todo list, and the tools that were loaded. Plain text, under 400 words."""

TITLE_PROMPT = "Give this chat a short title (at most 6 words, no quotes, no trailing period) based on the user's first message."


MODE_NOTES = {   # plan 27.4: what the chat's mode means for the model (the hub enforces it either way)
    "plan": "\nThis chat is in Plan mode: tools that read run; edits, commands and anything else that changes something "
            "are refused. Read and explain, and propose a plan (the files and the changes) for the user to approve; they can "
            "switch the mode to let you carry it out.",
    "manual": "",
    "accept_edits": "\nThis chat is in Accept edits mode: edits in workspace folders apply without asking (the user can undo a "
                    "whole turn); commands still ask.",
    "auto": "\nThis chat is in Auto mode: edits apply; commands ask unless they're judged safe.",
    "bypass": "\nThis chat is in Bypass mode: edits and sandbox commands run without asking in folders that allow it; "
              "anything on the user's machine still asks. Take care: say what you're about to do.",
}


def mode_note(mode: str) -> str:
    return MODE_NOTES.get(mode, "")
