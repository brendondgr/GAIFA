"""Which learned facts are saved without asking (plan memory-auto-learning 2.1).

The learner's model rates each fact it lists (`confidence`), quotes the user's words it comes from (`quote`) and
says whether it is sensitive. A fact becomes active on its own only when every rule below holds; otherwise it waits
in Review with the first reason that stopped it, which the page shows ("sensitive: health", "not sure: 0.55"):

- auto-approval is on (`auto_approve` in `data/agent/memory.json`);
- the quote is found in one of the user's own messages (spaces, case and quote marks aside): the model can't save
  what the user never said;
- `confidence ≥ auto_threshold`;
- not sensitive: neither the model's flag nor a word of the `always_review` categories;
- it doesn't replace a fact the user stated (their own words are only changed by them);
- it isn't still in the first person (`wording.first_person`).

A proposal the learner sees again becomes active once it was seen `auto_after_seen` times, unless it is sensitive.
Nothing here changes memory; the learner acts on the verdict, and every auto-approval is logged with Undo.
"""

from __future__ import annotations

import re
from typing import Any

from .wording import first_person

CATEGORIES: dict[str, tuple[str, ...]] = {
    "health": ("doctor", "diagnos", "medicat", "medicine", "therap", "illness", "disease", "symptom", "depress", "anxiety",
               "pregnan", "surgery", "hospital", "mental health", "adhd", "autis", "disorder", "allerg", "injur", "cancer",
               "diabet", "caffeine", "weight", "sick"),
    "money": ("money", "salary", "debt", "loan", "income", "financ", "bank", "invest", "mortgage", "bankrupt", "savings",
              "rent", "paycheck", "$", "€", "£", "net worth", "crypto", "tax"),
    "legal": ("lawyer", "lawsuit", "court", "arrest", "police", "visa", "immigra", "criminal", "legal", "sued"),
    "relationships": ("wife", "husband", "girlfriend", "boyfriend", "partner", "divorce", "dating", "married", "marriage",
                      "family", "mother", "father", "mom", "dad", "son", "daughter", "kids", "children", "sister", "brother"),
    "religion": ("church", "mosque", "synagogue", "temple", "faith", "religio", "pray", "christian", "muslim", "jewish",
                 "hindu", "buddhis", "atheis"),
    "politics": ("vote", "voted", "democrat", "republican", "politic", "election", "liberal", "conservative", "party member"),
    "sexuality": ("gay", "lesbian", "bisexual", "sexual", "queer", "transgender", "nonbinary", "non-binary"),
}

DEFAULTS: dict[str, Any] = {"auto_approve": True, "auto_threshold": 0.8, "auto_after_seen": 2,
                            "always_review": list(CATEGORIES)}


def settings(raw: dict[str, Any]) -> dict[str, Any]:
    """The auto-approval settings from memory.json's, with their defaults."""
    return {**DEFAULTS, **{k: raw[k] for k in DEFAULTS if k in raw}}


def _flat(s: str) -> str:
    s = (s or "").lower().replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", s).strip(" \t\n\"'.,;:!?…")


def grounded(quote: Any, said: list[str]) -> bool:
    """Whether `quote` is in one of the user's messages (`said`), spaces, case, quote marks and end punctuation aside."""
    q = _flat(quote) if isinstance(quote, str) else ""
    return len(q) >= 3 and any(q in _flat(s) for s in said)


def sensitive(text: str, categories: list[str]) -> str | None:
    """The first of `categories` a word of `text` falls in, or None."""
    t = (text or "").lower()
    for cat in categories:
        for w in CATEGORIES.get(cat, ()):
            if not w.replace("-", "").isalpha() or " " in w:      # "$", "net worth": as written
                hit = w in t
            elif len(w) <= 5:                                    # "son", "tax": the whole word
                hit = re.search(rf"(?<![a-z]){re.escape(w)}(?![a-z])", t)
            else:                                                # "diagnos", "therap": a word that starts so
                hit = re.search(rf"(?<![a-z]){re.escape(w)}", t)
            if hit:
                return cat
    return None


def decide(cand: dict[str, Any], said: list[str], replaced: dict[str, Any] | None, cfg: dict[str, Any]) -> tuple[bool, str]:
    """(True, "") when the fact `cand` is saved without asking; else (False, why it waits). `said` is the user's
    messages in the part of the chat it came from; `replaced` the held fact it replaces, if any."""
    if not cfg["auto_approve"]:
        return False, "auto-approval is off"
    if cand.get("first_person") or first_person(cand.get("text") or ""):
        return False, "worded as the user"
    cat = sensitive(cand.get("text") or "", list(cfg["always_review"]))
    if cat:
        return False, f"sensitive: {cat}"
    if cand.get("sensitive") is True:
        return False, "sensitive"
    if replaced is not None and replaced.get("source") == "stated":
        return False, "would change something you said"
    if not grounded(cand.get("quote"), said):
        return False, "not in your words"
    try:
        conf = float(cand.get("confidence"))
    except (TypeError, ValueError):
        return False, "not sure"
    if conf < float(cfg["auto_threshold"]):
        return False, f"not sure: {conf:.2f}"
    return True, ""


def seen_enough(fact: dict[str, Any], cfg: dict[str, Any]) -> bool:
    """A proposal said again often enough to be saved without asking."""
    return (bool(cfg["auto_approve"]) and fact.get("state") == "proposed" and int(fact.get("seen") or 0) >= int(cfg["auto_after_seen"])
            and not first_person(fact.get("text") or "") and sensitive(fact.get("text") or "", list(cfg["always_review"])) is None)
