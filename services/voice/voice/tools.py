"""Tools in a voice conversation (plan voice-speech-model Phase 5): a few the user picked, run through the hub.

`[voice_mode] tools` (Settings → Speech → Voice mode) names at most six. Each call goes to the hub as an
unattended call of this chat (`POST /api/tools/{name}/call`, origin `{service: "voice", thread, unattended}`):
what the chat's permissions allow runs, and what would ask is refused, never a card in the middle of a sentence.
The speech model is then told why, to say so. Two tools are the mod's own: `time_now`, and `ask_chat`
(`[voice_mode] ask_chat`), which hands your question to the chat's own model and gives its answer back to be said.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from .hub import Hub, HubError

log = logging.getLogger(__name__)

MAX_TOOLS = 6
RESULT_CHARS = 2000            # of a tool's result, for a 32K model that then speaks
DESCRIPTION_CHARS = 320
ASK_WAIT_S = 180.0

TIME_NOW = {"type": "function", "name": "time_now", "description": "The current date, weekday and time.",
            "parameters": {"type": "object", "properties": {}}}
ASK_CHAT = {"type": "function", "name": "ask_chat",
            "description": "Hand the user's question to the chat's main assistant, which is smarter and can read files, search and "
                           "use tools. Use it for anything you can't answer well yourself. You then say its answer in your own words.",
            "parameters": {"type": "object", "properties": {"question": {"type": "string", "description": "The user's question, in full"}},
                           "required": ["question"]}}
#: what the page shows while a tool runs
WORDS = {"time_now": "Checking the time…", "ask_chat": "Asking the chat’s model…", "web_search": "Searching the web…"}


def words_for(name: str) -> str:
    if name in WORDS:
        return WORDS[name]
    return "Looking at your calendar…" if name.startswith("calendar_") else f"Using {name.replace('_', ' ')}…"


def slim(tool: dict[str, Any]) -> dict[str, Any]:
    """A hub tool as a realtime function: its name, a short description and its parameters."""
    desc = " ".join(str(tool.get("description") or tool.get("summary") or "").split())
    if len(desc) > DESCRIPTION_CHARS:
        desc = desc[:DESCRIPTION_CHARS].rsplit(" ", 1)[0] + "…"
    params = tool.get("parameters") or {"type": "object", "properties": {}}
    return {"type": "function", "name": tool["name"], "description": desc, "parameters": params}


def short(result: Any, limit: int = RESULT_CHARS) -> str:
    text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, default=str)
    return text if len(text) <= limit else text[:limit] + "… (cut)"


class ToolBox:
    def __init__(self, hub: Hub, thread: str | None, names: list[str], ask_chat: bool = False) -> None:
        self.hub, self.thread = hub, thread
        self.names = [n for n in dict.fromkeys(names) if n != "ask_chat"][:MAX_TOOLS]
        self.ask_chat = bool(ask_chat and thread)
        self.defs: list[dict[str, Any]] = []
        self.asked = False                     # this turn went to the chat's model: the chat already holds it

    async def load(self) -> list[dict[str, Any]]:
        """The tools as the session gets them; a name the hub doesn't know is left out."""
        defs: list[dict[str, Any]] = []
        for name in self.names:
            if name == "time_now":
                defs.append(TIME_NOW)
                continue
            try:
                defs.append(slim(await self.hub.tool(name)))
            except HubError as e:
                log.warning("voice tool %s left out: %s", name, e.detail)
        if self.ask_chat:
            defs.append(ASK_CHAT)
        self.defs = defs
        return defs

    async def run(self, name: str, arguments: str, heard: str = "") -> tuple[str, str]:
        """Run one call: (`done` | `refused` | `failed`, what the model is told)."""
        if name not in {d["name"] for d in self.defs}:
            return "failed", json.dumps({"error": f"there is no tool {name}"})
        try:
            args = json.loads(arguments or "{}")
            if not isinstance(args, dict):
                raise ValueError("the arguments aren't an object")
        except ValueError as e:
            return "failed", json.dumps({"error": f"bad arguments: {e}"})
        if name == "time_now":
            return "done", json.dumps({"now": time.strftime("%A %d %B %Y, %H:%M"), "timezone": time.strftime("%Z")})
        if name == "ask_chat":
            return await self._ask(str(args.get("question") or "").strip(), heard)
        try:
            r = await self.hub.call_tool(name, args, self.thread)
        except HubError as e:
            return "failed", json.dumps({"error": e.detail})
        status = r.get("status")
        if status == "done":
            return "done", short(r.get("result"))
        err = r.get("error") or {}
        if status in ("denied", "needs_approval"):
            return "refused", json.dumps({"refused": "This needs the user's approval, which can't be given by voice. "
                                                     "Tell the user to do it in the chat instead.", "why": err.get("detail") or status})
        if status == "running":
            return "failed", json.dumps({"error": "it is still running; tell the user to look in the chat"})
        return "failed", json.dumps({"error": err.get("detail") or f"the tool ended with {status}"})

    async def _ask(self, question: str, heard: str) -> tuple[str, str]:
        text = heard.strip() or question            # the chat gets your own words when they were written down
        if not text:
            return "failed", json.dumps({"error": "no question"})
        try:
            sent = await self.hub.voice_ask(self.thread, text)
            self.asked = True
            ans = await self.hub.voice_answer(self.thread, sent["seq"], ASK_WAIT_S)
        except HubError as e:
            return "failed", json.dumps({"error": e.detail})
        if ans.get("state") != "done":
            return "failed", json.dumps({"error": "The chat's model hasn't finished. Tell the user the answer will be in the chat."})
        return "done", json.dumps({"answer": short(ans.get("text") or "", 1500),
                                   "say": "Tell the user this answer in one to three spoken sentences."}, ensure_ascii=False)
