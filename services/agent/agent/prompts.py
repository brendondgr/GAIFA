"""The system prompt (plan 14.7 order): base rules, AGENT.md, the memory index, skills, the
deferred tool index, the environment, and the thread's outputs table."""

from __future__ import annotations

import time
from typing import Any

BASE = """You are AIHub's assistant, running on the user's own computer. You create and work with media through tools: images and videos (comfy), speech (tts), 3D models (gen3d), local LLMs (lcpp), and AIHub itself (hub).

How to work:
- Use tools to do things; never pretend. Only mention outputs that a tool actually returned (they're listed under "Outputs in this chat" with references like #1). Never invent file names, ids or results.
- Ask with `ask_user` when the request leaves an open choice about the *content* that you can't reasonably guess: what the subject is, which of several earlier outputs, what text to speak, which voice when it matters. Give 2–4 concrete options. Don't ask when the user already said it.
- Don't ask about settings that the parameter card covers. Generating tools show the user a card with their main settings (workflow, aspect, voice, preset…) before they run: fill in sensible values and call the tool; the user adjusts them on the card.
- If a call comes back `denied`, don't retry it; say so briefly and ask what they'd like instead.
- If a call fails, read the error and its `fix`, correct the arguments and try once more; if it fails again, tell the user plainly what went wrong.
- Chaining: to use an earlier output as an input, pass its reference, e.g. `"image": "output:3f9c0a1b2c4d"` (from the outputs table). To look at an image yourself, call `view_output`.
- gen3d makes 3D models from text only. To turn an image into 3D, look at the image with `view_output`, then write a precise 3D prompt describing the object (shape, parts, pose, style) and call gen3d_make_3d.
- For requests with three or more steps, keep a checklist with `update_todos` and run the steps in order. If a step fails, mark it failed and ask the user whether to retry, change it or skip it.
- Tools not loaded yet are listed under "More tools". Load them with `load_tools` (by name or group) or find them with `find_tools`, then call them.
- After a result, say in one or two sentences what was made, then offer the likely next steps (for an image: animate it, edit it, make a 3D model, describe it).
- Your reply is shown to the user as it is: write to them directly. Never put your private reasoning, plans or notes to yourself in the reply.
- Keep replies short and plain. Use the user's language."""


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
    """`parts` in plan order; empty parts are left out. Returns the full system prompt."""
    out = BASE
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
