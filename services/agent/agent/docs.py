"""Attached documents (plan 24.5, 24.9): each attached text or document is described once at `send`
(so a rebuild never refetches) and goes into the message whole or as a card.

- **Settings** (Settings → Agent, kept in `data/agent/documents.json` over the env defaults):
  `inline_tokens`, how big a document may be to go in whole on its own (default `AGENT_INLINE_TOKENS`,
  6000; `"window"` means up to the model's window), and `reply_reserve`, the tokens kept free for the
  reply and tools (default 4096).
- **Room** = the model's window − the reserve − what the chat already uses (the meter). Documents
  attached together share it, in order.
- **Per attachment** (`auto` unless the chip says otherwise, remembered for the chat in its
  `settings.doc_mode`): `auto` goes whole up to `inline_tokens` and the room; `whole` goes whole if it
  fits the room, else it says how much didn't fit and falls back to a card; `card` is always a card.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import context as ctx

if TYPE_CHECKING:
    from .loop import Agent

log = logging.getLogger("agent.docs")

FILE = "documents.json"
MODES = ("auto", "whole", "card")
WINDOW = "window"
MAX_FETCH = 48000  # characters per text window from the hub


class SettingsError(ValueError):
    pass


def defaults(cfg: Any) -> dict[str, Any]:
    return {"inline_tokens": cfg.inline_tokens, "reply_reserve": cfg.reply_reserve}


def load(data: Path | None, cfg: Any) -> dict[str, Any]:
    out = defaults(cfg)
    try:
        saved = json.loads((Path(data) / FILE).read_text()) if data else {}
        out.update({k: v for k, v in saved.items() if k in out})
    except (OSError, ValueError):
        pass
    return out


def save(data: Path, cfg: Any, patch: dict[str, Any]) -> dict[str, Any]:
    cur = load(data, cfg)
    if "inline_tokens" in patch:
        v = patch["inline_tokens"]
        if v != WINDOW and not (isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 10_000_000):
            raise SettingsError('inline_tokens: a number of tokens (0 or more), or "window" for the model\'s whole window')
        cur["inline_tokens"] = v
    if "reply_reserve" in patch:
        v = patch["reply_reserve"]
        if not (isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 1_000_000):
            raise SettingsError("reply_reserve: a number of tokens, 0 or more")
        cur["reply_reserve"] = v
    Path(data).mkdir(parents=True, exist_ok=True)
    tmp = Path(data) / (FILE + ".part")
    tmp.write_text(json.dumps(cur, indent=1))
    os.replace(tmp, Path(data) / FILE)
    return cur


async def _whole_text(agent: Agent, oid: str, first: dict[str, Any]) -> str:
    parts, nxt = [first["text"]], first["next_offset"]
    while nxt is not None:
        w = await agent.hub.output_text(oid, offset=nxt, limit=MAX_FETCH)
        parts.append(w["text"])
        nxt = w["next_offset"]
    return "".join(parts)


async def describe(agent: Agent, tid: str, thread: dict[str, Any], ids: list[str],
                   modes: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """The `docs` of a user event: #n, size, outline, the mode asked for, and the text when it goes whole
    (or `fallback`, why it didn't)."""
    model = thread.get("model") or agent.cfg.model
    s = load(agent.cfg.data, agent.cfg)
    window = await agent.window(model, tid)
    used = (await agent.meter(tid, model))["used"]
    room = max(0, window - int(s["reply_reserve"]) - used)
    limit = room if s["inline_tokens"] == WINDOW else min(int(s["inline_tokens"]), room)
    default_mode = ((thread.get("settings") or {}).get("doc_mode")) or "auto"
    n0 = len(ctx.outputs(agent.store.events(tid, types=("tool_result", "user"))))
    out: list[dict[str, Any]] = []
    library: str | None | bool = False           # plan 28.3: looked up once, only when a document is that long
    for oid in ids:
        mode = (modes or {}).get(oid) or default_mode
        mode = mode if mode in MODES else "auto"
        try:
            o = await agent.hub.output(oid)
            if o.get("kind") not in ("text", "document"):
                continue
            w = await agent.hub.output_text(oid, limit=MAX_FETCH)
        except Exception as e:  # noqa: BLE001: it stays a plain attachment
            log.info("describing attachment %s: %s", oid, e)
            continue
        d: dict[str, Any] = {"ref": f"#{n0 + len(out) + 1}", "id": oid, "name": o.get("title") or oid, "kind": o["kind"],
                             "subtype": o.get("subtype"), "tokens": w["tokens"], "pages": w["pages"], "lines": w["lines"],
                             "outline": [{k: x[k] for k in ("level", "title", "page", "line") if x.get(k) is not None}
                                         for x in w["outline"][:30]],
                             "mode": mode, "inline": False}
        if w.get("scanned"):
            d["scanned"] = w["scanned"][:50]
        if w.get("notes"):
            d["notes"] = w["notes"][:5]
        has_text = w["total_chars"] > 0
        if mode == "whole" and has_text and w["tokens"] > room:
            d["fallback"] = (f"{d['name']} is ~{w['tokens']:,} tokens, but this chat has room for ~{room:,} "
                             f"(the model's {window:,}-token window, less the {int(s['reply_reserve']):,}-token reserve for the reply "
                             f"and what the chat already holds), so ~{w['tokens'] - room:,} tokens didn't fit. It was sent as a card; "
                             "the agent reads it in parts.")
        elif has_text and ((mode == "whole") or (mode == "auto" and w["tokens"] <= limit)):
            try:
                d["text"] = w["text"] if w["next_offset"] is None else await _whole_text(agent, oid, w)
                d["inline"] = True
                room -= w["tokens"]
                limit = room if s["inline_tokens"] == WINDOW else min(int(s["inline_tokens"]), room)
            except Exception as e:  # noqa: BLE001
                d["fallback"] = f"couldn't fetch all of {d['name']} ({e}); it was sent as a card"
        if (w["pages"] or 0) > ctx.LIBRARY_PAGES and not d["inline"]:
            if library is False:
                library = await library_tool(agent)
            if library:
                d["library"] = library
        out.append(d)
    return out


async def library_tool(agent: Agent) -> str | None:
    """The embed mod's search tool, if it's in the catalog (deleting the mod removes the hint, plan 28.3)."""
    try:
        return next((t["name"] for t in await agent.hub.index() if t["name"] == ctx.LIBRARY_TOOL), None)
    except Exception:  # noqa: BLE001: no hint then
        return None
