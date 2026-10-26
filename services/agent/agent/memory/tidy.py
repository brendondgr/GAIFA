"""Tidying memory every night (plan structured-memory 4.2), with the learner's nightly run.

- **Ended facts:** an active fact whose `valid_until` has passed is retired (a stated one is left as it is: it's
  already not current, and the user's own words are never changed by the agent).
- **Duplicate entries:** two active entities of the same kind whose names share most of their words (one name inside
  the other, or Jaccard ≥ 0.6), or whose embeddings are very close (≥ 0.92), become a proposed merge, once.
- **Summaries:** an entity with facts newer than its summary gets one sentence from its current facts (10 a night).
- **Fading:** an inferred fact nobody used for `fade_days` (`data/agent/memory.json`, default 180) is proposed for retiring.

Merges and retirements are proposals (`proposed` events whose evidence carries the action); nothing is merged or
retired without the user's approval, and no stated fact is touched.
"""

from __future__ import annotations

import logging
import time
from itertools import combinations
from typing import Any

from .model import norm
from .store import MemoryStore

log = logging.getLogger("agent.memory.tidy")
SUMMARIES = 10
FADE_DAYS = 180
CLOSE = 0.92

SUMMARY = """Write one short sentence that says what "{name}" ({kind}) is, from these facts. Only what they say; no preamble.

{facts}"""


def _similar(a: str, b: str) -> bool:
    x, y = set(a.split()), set(b.split())
    if not x or not y:
        return False
    inside = f" {a} " in f" {b} " or f" {b} " in f" {a} "
    return inside or len(x & y) / len(x | y) >= 0.6


def proposed_actions(m: MemoryStore) -> set[tuple[str, ...]]:
    """Merges and retirements already proposed, rejected or done: never proposed twice."""
    import json
    out: set[tuple[str, ...]] = set()
    for f in m._rows("SELECT evidence FROM mem_facts WHERE kind = 'event' AND source = 'inferred'"):
        for ev in json.loads(f["evidence"] or "[]"):
            if ev.get("action") == "merge":
                out.add(("merge", *sorted((ev["entity"], ev["into"]))))
            elif ev.get("action") == "retire":
                out.add(("retire", ev["fact"]))
    return out


def ended(m: MemoryStore) -> int:
    rows = m._rows("SELECT id FROM mem_facts WHERE state = 'active' AND source != 'stated' AND valid_until IS NOT NULL "
                   "AND valid_until <= ?", (m.today(),))
    for r in rows:
        m.set_fact_state(r["id"], "retired", by="tidy")
    return len(rows)


async def duplicates(m: MemoryStore, hub: Any) -> int:
    done, n = proposed_actions(m), 0
    ents = [e for e in m.entities() if e["id"] != "user"]
    names = {e["id"]: [e["norm"], *(norm(a) for a in m.aliases(e["id"]))] for e in ents}
    pairs = set()
    for a, b in combinations(ents, 2):
        if a["kind"] == b["kind"] and any(_similar(x, y) for x in names[a["id"]] for y in names[b["id"]]):
            pairs.add(tuple(sorted((a["id"], b["id"]))))
    if hub is not None:                                # very close in meaning (the embed mod's memory collection)
        for e in ents:
            try:
                r = await hub._json("POST", "/api/s/embed/v1/texts/memory/search",
                                    json={"query": f"{e['name']} {e['summary']}".strip(), "limit": 4,
                                          "ids": [f"entity:{x['id']}" for x in ents if x["id"] != e["id"]]})
            except Exception:  # noqa: BLE001: names alone, then
                break
            for h in r.get("results") or []:
                other = m.entity_row(h["id"].partition(":")[2])
                if other and other["kind"] == e["kind"] and h.get("score", 0) >= CLOSE:
                    pairs.add(tuple(sorted((e["id"], other["id"]))))
    for a_id, b_id in sorted(pairs):
        if ("merge", a_id, b_id) in done:
            continue
        a, b = m.entity_row(a_id), m.entity_row(b_id)
        keep, drop = (a, b) if len(m.facts_of(a_id)) >= len(m.facts_of(b_id)) else (b, a)
        m.add_fact(f"Merge {drop['name']} into {keep['name']}", about=[keep["id"], drop["id"]], kind="event", source="inferred",
                   evidence=[{"action": "merge", "entity": drop["id"], "into": keep["id"]}], by="tidy")
        n += 1
    return n


async def summaries(m: MemoryStore, llm: Any, model: str) -> int:
    n = 0
    for e in m.entities():
        if e["id"] == "user" or n >= SUMMARIES:
            continue
        facts = m.facts_of(e["id"])
        if not facts or max(f["updated"] for f in facts) <= e["updated"]:
            continue
        reply = await llm.chat(model, [{"role": "user", "content": SUMMARY.format(
            name=e["name"], kind=e["kind"], facts="\n".join(f"- {f['text']}" for f in facts[:30]))}], stream=False)
        text = " ".join((reply.text or "").split())[:300].strip().strip('"')
        if text:
            m.update_entity(e["id"], summary=text, by="tidy")
            n += 1
    return n


def fading(m: MemoryStore, days: int = FADE_DAYS) -> int:
    done, n = proposed_actions(m), 0
    cut = time.time() - days * 86400
    for f in m._rows("SELECT * FROM mem_facts WHERE state = 'active' AND source = 'inferred' AND kind != 'event' "
                     "AND COALESCE(last_used, recorded) < ?", (cut,)):
        if ("retire", f["id"]) in done:
            continue
        ents = [r["entity"] for r in m._rows("SELECT entity FROM mem_fact_entities WHERE fact = ?", (f["id"],))]
        m.add_fact(f"Stop remembering: {f['text']}", about=ents, kind="event", source="inferred",
                   evidence=[{"action": "retire", "fact": f["id"]}], by="tidy")
        n += 1
    return n


async def run(agent: Any, fade_days: int = FADE_DAYS) -> dict[str, int]:
    m: MemoryStore = agent.memory
    out = {"ended": ended(m), "merges": await duplicates(m, agent.hub), "fading": fading(m, fade_days)}
    try:
        out["summaries"] = await summaries(m, agent.llm, agent.cfg.model)
    except Exception:  # noqa: BLE001: the model may be away tonight
        log.exception("memory summaries")
        out["summaries"] = 0
    log.info("memory tidied: %s", out)
    return out
