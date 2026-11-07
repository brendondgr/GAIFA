"""Comparing new facts with what memory holds (the learner's step 3, structured-memory 4.1; shared with imports,
plan memory-import 1.3).

For each new fact: a fact it says has ended ("no longer Blender", `ends_of`) replaces the newest current fact naming
that thing, without asking the model (`ended_fact`, memory-auto-learning 3.2); otherwise its five nearest current
facts (`memory_search`) go to the model, which answers one operation per fact: `same`, `replaces`, `adds` or `skip`.
An id the model made up counts as `adds`.
"""

from __future__ import annotations

import re
from typing import Any, Awaitable, Callable

from .model import norm
from .search import search
from .store import MemoryStore

DECIDE = """You keep an assistant's memory. For each new fact below, compare it with the facts memory already holds about the same things, and choose one:
- "same": it says what held fact <id> says (nothing changes)
- "replaces": it makes held fact <id> out of date (a change, a correction, a newer value; a new fact that says the user no longer does, likes or uses what <id> says replaces it)
- "adds": it is new
- "skip": it isn't worth keeping
Answer with JSON only: {{"decisions": [{{"n": 1, "op": "same|replaces|adds|skip", "id": "the held fact's id, or null"}}]}}

{items}"""

_ENDS = [re.compile(p, re.I) for p in (
    r"\bno longer (?:using |into |use |uses |with |likes? |a fan of |working (?:on|with) )?([A-Z][\w.+#-]*)",
    r"\bnot (?:using |into |with )?([A-Z][\w.+#-]*) any ?more", r"\binstead of ([A-Z][\w.+#-]*)",
    r"\bswitched (?:away )?from ([A-Z][\w.+#-]*)", r"\bmoved (?:away )?from ([A-Z][\w.+#-]*)", r"\bstopped (?:using )?([A-Z][\w.+#-]*)")]


def ends_of(c: dict[str, Any]) -> list[str]:
    """What a learned fact says the user stopped (memory-auto-learning 3.2): the model's `ends`, and names after "no
    longer", "not … anymore", "instead of", "switched from" in the fact or its quote."""
    out = [str(t).strip() for t in c.get("ends") or [] if isinstance(t, str) and str(t).strip()]
    for text in (c.get("text"), c.get("quote")):
        for rx in _ENDS:
            out += [m.group(1).rstrip(".,;") for m in rx.finditer(text or "") if m.group(1)[:1].isupper()]
    return list(dict.fromkeys(t for t in out if norm(t) and norm(t) not in ("the", "it", "that", "this")))


def ended_fact(m: MemoryStore, terms: list[str]) -> str | None:
    """The newest current fact that names one of `terms` as something the user has (not one that already says it
    ended): the fact a "no longer X" replaces."""
    if not terms:
        return None
    pats = [re.compile(rf"(?<![\w]){re.escape(t)}(?![\w])", re.I) for t in terms]
    for f in m.facts(state="active", current=True, limit=500):
        if f["kind"] == "event" or any(rx.search(f["text"]) for rx in _ENDS):
            continue
        if any(p.search(f["text"]) for p in pats):
            return f["id"]
    return None


async def compare(m: MemoryStore, hub: Any, ask: Callable[[str], Awaitable[dict[str, Any] | None]], cands: list[dict[str, Any]],
                  meaning_wait: float = 10, batch: int = 0) -> list[tuple[str, str | None]]:
    """(op, held fact id) for each of `cands` (dicts with `text`, maybe `ends` and `quote`), in order. `ask` sends a
    prompt to the model and returns its JSON; `batch` > 0 asks about that many facts at a time."""
    held: list[list[dict[str, Any]]] = []
    for c in cands:
        r = await search(m, hub, c["text"], limit=5, meaning_wait=meaning_wait)
        held.append([f for f in r["facts"] if f.get("current", True)][:5])
    ops: list[tuple[str, str | None]] = [("adds", None)] * len(cands)
    for i, c in enumerate(cands):                       # "…, no longer Blender": the held Blender fact, without asking
        old = ended_fact(m, ends_of(c))
        if old is not None:
            ops[i] = ("replaces", old)
    ask_ix = [i for i, h in enumerate(held) if h and ops[i][0] == "adds"]
    size = batch or len(ask_ix) or 1
    for start in range(0, len(ask_ix), size):
        part = ask_ix[start:start + size]
        items = "\n\n".join(f"{k}. NEW: {cands[i]['text']}\n   HELD: " + "; ".join(f"{h['id']}: {h['text']}" for h in held[i])
                            for k, i in enumerate(part, 1))
        got = await ask(DECIDE.format(items=items)) or {}
        for d in got.get("decisions") or []:
            try:
                i = part[int(d.get("n")) - 1]
            except (TypeError, ValueError, IndexError):
                continue
            op, fid = str(d.get("op") or "adds"), d.get("id")
            if op in ("same", "replaces") and fid not in {h["id"] for h in held[i]}:
                op, fid = "adds", None                     # an id it made up: treat it as new
            ops[i] = (op if op in ("same", "replaces", "adds", "skip") else "adds", fid)
    return ops
