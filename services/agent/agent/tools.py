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

from .show import TOOL as SHOW_TOOL  # noqa: E402 - plan 47.1

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
     "it, write from it or check it; `page` shows a PDF's page as an image (figures, tables, scanned pages). For text and "
     "documents it gives the start of the text: read the rest with hub_read_document. `ref` is #n or output:<id>.",
     "parameters": {"type": "object", "properties": {"ref": {"type": "string"},
                                                    "page": {"type": "integer", "minimum": 1, "description": "A PDF's page (1-based)"}},
                    "required": ["ref"]}},
    {"name": "read_result", "description": "Read more of an earlier tool result that was cut or cleared: `seq` is the number "
     "in its note.",
     "parameters": {"type": "object", "properties": {"seq": {"type": "integer"}, "offset": {"type": "integer", "default": 0},
                                                    "limit": {"type": "integer", "default": 12000}}, "required": ["seq"]}},
    {"name": "chat_search", "description": "Find the user's earlier chats by meaning (plan 28.5): what a chat was about, "
     "in words. Returns each chat's title, date, a short summary and its link (#/chat/<id>), best first, so you can say "
     "\"you did this in the chat on 10-14\". Only chats that have been quiet a while have summaries.",
     "parameters": {"type": "object", "properties": {"query": {"type": "string"},
                                                    "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5}},
                    "required": ["query"]}},
    {"name": "memory_search", "description": "Search what you know about the user and their projects, people, tools and "
     "topics, by name (old names too), words and meaning. Use it before asking what they may have told you.",
     "parameters": {"type": "object", "properties": {"query": {"type": "string"},
                                                    "entity": {"type": "string", "description": "Only about this (a name or path)"},
                                                    "history": {"type": "boolean", "description": "Also replaced and ended facts, with when they held (what the user used or liked before)"}},
                    "required": ["query"]}},
    SHOW_TOOL,
    {"name": "remember", "description": "Save a lasting fact the user told you (e.g. 'prefers 16:9 images'). `about`: what "
     "it's about, by name or path (projects/GAIFA); leave it out for the user.",
     "parameters": {"type": "object", "properties": {"text": {"type": "string"},
                                                    "about": {"type": "array", "items": {"type": "string"}},
                                                    "kind": {"type": "string", "enum": ["preference", "fact", "interest", "event"]}},
                    "required": ["text"]}},
]
from .projects.tools import NAMES as PROJECT_NAMES, TOOLS as PROJECT_TOOLS  # noqa: E402 - plan projects 3.4
from .tasks.notes import NAMES as TASK_NAMES, TOOLS as TASK_TOOLS  # noqa: E402 - scheduled-tasks 2.4
from .workflows.tool import NAMES as WORKFLOW_NAMES, TOOLS as WORKFLOW_TOOLS  # noqa: E402 - agent-workflows 1.3

LOCAL_NAMES = {t["name"] for t in LOCAL} | PROJECT_NAMES | TASK_NAMES | WORKFLOW_NAMES   # a project chat's, a scheduled run's and a workflow's tools run locally too
READ_ONLY_LOCAL = LOCAL_NAMES - {"remember", "task_note"}


def function(t: dict[str, Any], note: str | None = None) -> dict[str, Any]:
    desc = t.get("description", "")
    if note and note.strip():
        desc += "\n" + note.strip()            # the harness's tools/<name>.md (plan 22.2)
    if t.get("examples"):
        import json

        desc += "\nExample arguments: " + "; ".join(json.dumps(e, separators=(",", ":")) for e in t["examples"][:2])
    if t.get("ask"):
        desc += f"\n(The user confirms {', '.join(t['ask'])} on a card before it runs.)"
    return {"type": "function", "function": {"name": t["name"], "description": desc, "parameters": t.get("parameters") or {"type": "object"}}}


CALLABLE = ("on", "starts_on_use")   # capability-enablement 2.1: a stopped mod's tools stay callable (the call starts it)


def usable(t: dict[str, Any]) -> bool:
    """The tool's mod can be used (its `state` from the hub's catalog); the rest are listed under Off on this machine."""
    return t.get("state", "on") in CALLABLE


def group_of(t: dict[str, Any]) -> str:
    """A tool's group in the chat: its mod's own group (mcp-client 4.1: `mcp:<server>`), else its mod."""
    return t.get("group") or t["mod"]


def hidden_group(g: str) -> bool:
    """An MCP server's group: hidden in a chat until a skill, an @-mention or the composer turns it on."""
    return g.startswith("mcp:")


class ToolSet:
    """The tools one thread sees right now. A group is a mod, or a mod's own group (an MCP server, `mcp:<id>`);
    `pinned` and `disabled` hold either. An MCP server's group is hidden (not listed, not loaded, not found) until it
    is on in the chat (`mcp_on`), pinned, or one of its tools was loaded."""

    def __init__(self, hub: HubAPI, settings: dict[str, Any], all_tools: bool = False) -> None:
        self.hub = hub
        # Every tool loaded up front: for servers that constrain tool calls with a grammar (llama.cpp),
        # where the model can only name tools it was given; deferred ones would be unreachable.
        self.all_tools = all_tools
        self.loaded: list[str] = list(settings.get("loaded") or [])
        self.pinned: set[str] = set(settings.get("pinned") or [])
        self.disabled: set[str] = set(settings.get("disabled") or [])
        self.on: set[str] = set(settings.get("mcp_on") or [])
        self.project: str | None = settings.get("project") or None   # a project chat has the project tools (plan projects 3.4)
        self.task: str | None = settings.get("task") or None         # a scheduled run has task_note (scheduled-tasks 2.4)
        self.spawn = False                       # the `agent` tool: set with the Sub-agents prompt part (agent-workflows 1.3)
        self.spawn_more = False                  # agent_wait, …_send, …_stop, …_list, …_review: once the chat has sub-agents (5.2)
        self.child = bool(settings.get("spawn"))  # a sub-agent: no remember, no agent_memory_* (agent-workflows 2.4)
        self.index: list[dict[str, Any]] = []
        self.full: dict[str, dict[str, Any]] = {}
        self.notes: dict[str, str] = {}              # tool → the harness's note (plan 22.2)

    def off(self, t: dict[str, Any]) -> bool:
        return (t["mod"] in self.disabled or group_of(t) in self.disabled or (self.child and t["name"].startswith("agent_memory_"))
                or t["name"].startswith("agent_chat_"))    # other agents' chat tools (/mcp): a chat here has its agent tool

    def hidden(self, t: dict[str, Any]) -> bool:
        g = group_of(t)
        return hidden_group(g) and g not in self.on and g not in self.pinned and t["name"] not in self.loaded

    async def refresh(self) -> None:
        try:
            self.index = await self.hub.index()
        except Exception:  # noqa: BLE001 - the hub may be restarting: keep what we had
            self.index = self.index or []
        names = [t["name"] for t in self.index if not self.off(t) and not self.hidden(t) and usable(t) and
                 (self.all_tools or t["core"] or t["mod"] in self.pinned or group_of(t) in self.pinned or t["name"] in self.loaded)]
        self.full = {t["name"]: t for t in await self.hub.tools(names)} if names else {}

    def by_name(self, name: str) -> dict[str, Any] | None:
        return next((t for t in self.index if t["name"] == name), None)

    def local(self) -> list[dict[str, Any]]:
        return ([t for t in LOCAL if not (self.child and t["name"] == "remember")]
                + (PROJECT_TOOLS if self.project else []) + (TASK_TOOLS if self.task else [])
                + (WORKFLOW_TOOLS[:1] if self.spawn else []) + (WORKFLOW_TOOLS[1:] if self.spawn and self.spawn_more else []))

    def visible(self) -> set[str]:
        return set(self.full) | {t["name"] for t in self.local()}

    def functions(self) -> list[dict[str, Any]]:
        return [function(t, self.notes.get(t["name"])) for t in self.local()] + [function(t, self.notes.get(t["name"])) for t in self.full.values()]

    def deferred(self) -> list[dict[str, Any]]:
        return [t for t in self.index if t["name"] not in self.full and not self.off(t) and not self.hidden(t) and usable(t)]

    def unusable(self) -> list[dict[str, Any]]:
        """Tools that exist but can't run here now (not set up, off, failed, broken, or off by the mod), for the prompt."""
        return [t for t in self.index if not usable(t) and not self.off(t) and not self.hidden(t)]

    def risk(self, name: str) -> str:
        if name in LOCAL_NAMES:
            return "read" if name in READ_ONLY_LOCAL else "write"
        t = self.full.get(name) or self.by_name(name) or {}
        return t.get("risk", "write")

    def load(self, names: list[str] | None = None, group: str | None = None) -> tuple[list[str], list[str]]:
        """(loaded now, unknown). Loading an MCP server's group turns it on in the chat."""
        want = list(names or [])
        if group:
            want += [t["name"] for t in self.index if t["mod"] == group or group_of(t) == group]
            if hidden_group(group):
                self.on.add(group)
        known = {t["name"] for t in self.index}
        ok = [n for n in want if n in known and not self.off(self.by_name(n)) and usable(self.by_name(n))]  # type: ignore[arg-type]
        bad = [n for n in want if n not in ok]
        for n in ok:
            if n not in self.loaded:
                self.loaded.append(n)
        return ok, bad
