"""Learned facts in the third person (plan memory-auto-learning 1.2–1.3).

The learner writes what the user said as facts about the user ("The user prefers…"), never as their own words ("I
prefer…"). `first_person` catches a fact that slipped through, `reword` asks the model to rewrite such facts once, and
`reword_saved` does it for inferred facts already in memory (each change logged, so it can be undone). A stated fact
(what the user asked to be remembered) keeps the user's words: nothing here touches one.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from ..learn.loop import _json

log = logging.getLogger("agent.memory.wording")

# "I" only as a capital; the rest in any case. Quoted words ("…", “…”) don't count: a fact may quote the user.
_I = re.compile(r"(?<![\w'’])I(?:['’](?:m|ve|d|ll))?(?![\w'’])")
_OTHER = re.compile(r"(?<![\w'’])(?:me|my|mine|myself|we|our|ours|ourselves)(?![\w'’])", re.I)
_QUOTED = re.compile(r"\"[^\"]*\"|“[^”]*”")

REWORD = """Rewrite each sentence below as a fact about the user, in the third person: "The user…", "Their…", never "I", "my", "me", "we" or "our". Keep the meaning exactly; change nothing else.

{items}

Answer with JSON only, one sentence per number, in the same order: {{"facts": ["…", "…"]}}"""


def first_person(text: str) -> bool:
    """Whether a fact speaks as the user ("I", "my", "we"…) outside quotation marks."""
    t = _QUOTED.sub(" ", text or "")
    return bool(_I.search(t) or _OTHER.search(t))


async def reword(llm: Any, model: str, texts: list[str]) -> list[str]:
    """`texts` rewritten in the third person by one call to `model`, in order. A sentence the model didn't rewrite
    (no JSON, a count that doesn't match, an empty one) comes back as it was; the caller checks `first_person` again."""
    if not texts:
        return []
    items = "\n".join(f"{i}. {t}" for i, t in enumerate(texts, 1))
    try:
        reply = await llm.chat(model, [{"role": "user", "content": REWORD.format(items=items)}], stream=False)
    except Exception as e:  # noqa: BLE001: the model may be away; the facts stay as they were
        log.warning("rewording failed: %s", e)
        return list(texts)
    got = (_json(reply.text or "") or {}).get("facts")
    if not isinstance(got, list) or len(got) != len(texts):
        return list(texts)
    return [g.strip() if isinstance(g, str) and g.strip() else t for g, t in zip(got, texts)]


async def reword_saved(agent: Any) -> dict[str, int]:
    """Every proposed or active inferred fact that `first_person` catches, rewritten (`fact_update` by the learner,
    undoable). Returns how many were rewritten and how many are still in the first person."""
    m = agent.memory
    rows = [f for f in m._rows("SELECT id, text FROM mem_facts WHERE source = 'inferred' AND state IN ('proposed', 'active') "
                                "ORDER BY recorded, id")
            if first_person(f["text"])]
    if not rows:
        return {"reworded": 0, "left": 0}
    model = await agent.llm.background_model(None, agent.cfg.model)
    if model is None:
        return {"reworded": 0, "left": len(rows)}
    new = await reword(agent.llm, model, [f["text"] for f in rows])
    done = 0
    for f, t in zip(rows, new):
        if t != f["text"] and not first_person(t):
            m.update_fact(f["id"], text=t, by="learner")
            done += 1
    return {"reworded": done, "left": len(rows) - done}
