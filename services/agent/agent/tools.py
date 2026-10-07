"""Tools on demand (plan 14.6): the local tools, and which hub tools a thread has loaded.

Always loaded: the local tools below and the hub catalog's `core` tools. The rest are listed by
group in the system prompt; `find_tools` / `load_tools` add their schemas to the thread
(`settings.loaded`, kept across compaction). A thread may pin groups (always loaded) or turn
them off (`settings.pinned` / `settings.disabled`, lists of mod ids); the hub refuses a disabled
group's tools too (they're denied in the call's mode).
"""

from __future__ import annotations

from typing import Any

from .hubapi import HubAPI

QUESTION = {
    "type": "object",
    "properties": {
        "question": {"type": "string", "description": "The question, ending with a question mark"},
        "header": {"type": "string", "description": "A 1–3 word label, e.g. \"Style\""},
        "options": {"type": "array", "minItems": 2, "maxItems": 4, "items": {
            "type": "object", "properties": {"label": {"type": "string"}, "description": {"type": "string"}},
            "required": ["label"]}, "description": "2–4 choices; the user can always type something else"},
        "multi_select": {"type": "boolean", "default": False},
    },
    "required": ["question", "options"],
}

LOCAL: list[dict[str, Any]] = [
    {"name": "ask_user", "description": "Ask the user 1–4 multiple-choice questions and wait for the answers. Use it for open "
     "choices about the content you can't guess (subject, which output, what to say). Each question has 2–4 options; "
     "the user may also type their own answer.",
     "parameters": {"type": "object", "properties": {"questions": {"type": "array", "minItems": 1, "maxItems": 4, "items": QUESTION}},
                    "required": ["questions"]}},
    {"name": "update_todos", "description": "Write the checklist for a multi-step request (3+ steps). Send the whole list each "
     "time with each item's state: pending, in_progress, done or failed.",
     "parameters": {"type": "object", "properties": {"items": {"type": "array", "items": {"type": "object", "properties": {
         "text": {"type": "string"}, "state": {"type": "string", "enum": ["pending", "in_progress", "done", "failed"]}},
         "required": ["text", "state"]}}}, "required": ["items"]}},
    {"name": "find_tools", "description": "Search the tools that aren't loaded yet by what they do. Returns names and summaries; "
     "then load the ones you need with load_tools.",
     "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
    {"name": "load_tools", "description": "Load tools so you can call them: by `names`, or a whole `group` (a mod id such as "
     "comfy, tts, gen3d).",
     "parameters": {"type": "object", "properties": {"names": {"type": "array", "items": {"type": "string"}},
                                                    "group": {"type": "string"}}}},
    {"name": "read_skill", "description": "Read a skill's instructions (or a memory topic with 'memory:<topic>') before doing "
     "that kind of task.",
     "parameters": {"type": "object", "properties": {"name": {"type": "string", "description": "e.g. comfy/choosing-a-workflow"}},
                    "required": ["name"]}},
    {"name": "view_output", "description": "Look at an output (an image, or a video's or 3D model's preview) so you can describe "
     "it, write from it or check it. `ref` is #n or output:<id>.",
     "parameters": {"type": "object", "properties": {"ref": {"type": "string"}}, "required": ["ref"]}},
    {"name": "read_result", "description": "Read more of an earlier tool result that was cut or cleared: `seq` is the number "
     "in its note.",
     "parameters": {"type": "object", "properties": {"seq": {"type": "integer"}, "offset": {"type": "integer", "default": 0},
                                                    "limit": {"type": "integer", "default": 12000}}, "required": ["seq"]}},
    {"name": "remember", "description": "Save a lasting fact or preference about the user (e.g. 'prefers 16:9 images'). "
     "Optional `topic` files it under a topic.",
     "parameters": {"type": "object", "properties": {"text": {"type": "string"}, "topic": {"type": "string"}},
                    "required": ["text"]}},
]
LOCAL_NAMES = {t["name"] for t in LOCAL}
READ_ONLY_LOCAL = LOCAL_NAMES - {"remember"}


def function(t: dict[str, Any]) -> dict[str, Any]:
    desc = t.get("description", "")
    if t.get("examples"):
        import json

        desc += "\nExample arguments: " + "; ".join(json.dumps(e, separators=(",", ":")) for e in t["examples"][:2])
    if t.get("ask"):
        desc += f"\n(The user confirms {', '.join(t['ask'])} on a card before it runs.)"
    return {"type": "function", "function": {"name": t["name"], "description": desc, "parameters": t.get("parameters") or {"type": "object"}}}


class ToolSet:
    """The tools one thread sees right now."""

    def __init__(self, hub: HubAPI, settings: dict[str, Any]) -> None:
        self.hub = hub
        self.loaded: list[str] = list(settings.get("loaded") or [])
        self.pinned: set[str] = set(settings.get("pinned") or [])
        self.disabled: set[str] = set(settings.get("disabled") or [])
        self.index: list[dict[str, Any]] = []
        self.full: dict[str, dict[str, Any]] = {}

    async def refresh(self) -> None:
        try:
            self.index = await self.hub.index()
        except Exception:  # noqa: BLE001 - the hub may be restarting: keep what we had
            self.index = self.index or []
        names = [t["name"] for t in self.index if t["mod"] not in self.disabled and
                 (t["core"] or t["mod"] in self.pinned or t["name"] in self.loaded)]
        self.full = {t["name"]: t for t in await self.hub.tools(names)} if names else {}

    def by_name(self, name: str) -> dict[str, Any] | None:
        return next((t for t in self.index if t["name"] == name), None)

    def visible(self) -> set[str]:
        return set(self.full) | LOCAL_NAMES

    def functions(self) -> list[dict[str, Any]]:
        return [function(t) for t in LOCAL] + [function(t) for t in self.full.values()]

    def deferred(self) -> list[dict[str, Any]]:
        return [t for t in self.index if t["name"] not in self.full and t["mod"] not in self.disabled]

    def risk(self, name: str) -> str:
        if name in LOCAL_NAMES:
            return "read" if name in READ_ONLY_LOCAL else "write"
        t = self.full.get(name) or self.by_name(name) or {}
        return t.get("risk", "write")

    def load(self, names: list[str] | None = None, group: str | None = None) -> tuple[list[str], list[str]]:
        """(loaded now, unknown)."""
        want = list(names or [])
        if group:
            want += [t["name"] for t in self.index if t["mod"] == group]
        known = {t["name"] for t in self.index}
        ok = [n for n in want if n in known and self.by_name(n)["mod"] not in self.disabled]  # type: ignore[index]
        bad = [n for n in want if n not in ok]
        for n in ok:
            if n not in self.loaded:
                self.loaded.append(n)
        return ok, bad
