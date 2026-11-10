"""The judge's eval items (plan 30.4), built from the sources in manifest.toml.

- **AgentDojo** (v1.2, MIT): each user task's request with the calls that complete it is `safe` (label allow); the
  same requests paired with an injection task's calls (what a planted instruction in an email, file or page wants)
  are `injection` (label ask). Reads (`get_*`, `search_*`, `read_*`, `list_*`, `check_*`) are left out of the
  injection side, since alone they change nothing; `get_webpage` becomes the hub's `web_fetch`.
- **Routine** (routine.py): commands, edits, fetches and GPU jobs the user asked for in so many words (allow).

Each item carries the steps before its call (`history`, for the judge's `context`): AgentDojo's from
agentdojo-context.jsonl (extract_context.py: the ground-truth calls before it, with their real outputs; for injection
items, with the planted attack), the routine items' from routine.HISTORY (a few have none).

The benchmark text stays in data/state/judge-bench/ (gitignored); only ids and metrics are committed.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .routine import HISTORY, ROUTINE
from .calendar import CALENDAR
from .scheduled import SCHEDULED

ROOT = Path(__file__).resolve().parents[4]
BENCH = ROOT / "data" / "state" / "judge-bench"
AGENTDOJO = BENCH / "agentdojo-v1.2.jsonl"
CONTEXT = BENCH / "agentdojo-context.jsonl"
READS = ("get_", "search_", "read_", "list_", "check_")
PAIRS = 3                            # user tasks each injection task is paired with


@dataclass
class Item:
    id: str
    source: str                      # agentdojo | routine | scheduled | calendar
    group: str                       # safe | injection | overreach (scheduled)
    label: str                       # allow | ask
    user: list[str]
    call: dict[str, Any]
    folder: dict[str, Any] | None = field(default=None)
    history: list[dict[str, Any]] = field(default_factory=list)   # the steps before the call (no user messages)
    planted: bool = False            # injection items: the attack text is in the history's results

    @property
    def scope(self) -> str:
        t = self.call["tool"]
        return ("command" if t in ("workspace_run", "workspace_python") else "fetch" if t == "web_fetch"
                else "edit" if t.startswith("workspace_") else "gpu" if self.call.get("estimate") else "action")


def to_call(c: dict[str, Any]) -> dict[str, Any]:
    if c["function"] == "get_webpage":
        url = str(c["args"].get("url", ""))
        return {"tool": "web_fetch", "args": {"url": url if "://" in url else "https://" + url}}
    return {"tool": c["function"], "args": c["args"]}


def agentdojo(path: Path = AGENTDOJO) -> list[Item]:
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    users = [r for r in rows if r["kind"] == "user"]
    items: list[Item] = []
    for u in users:
        reads_kept = 0
        for k, c in enumerate(u["calls"]):
            read = c["function"].startswith(READS) and c["function"] != "get_webpage"
            if read and reads_kept >= 1:
                continue
            reads_kept += read
            items.append(Item(f"ad-safe-{u['suite']}-{u['id']}-{k}", "agentdojo", "safe", "allow", [u["text"]],
                              to_call(c)))
    rng = random.Random(30)
    for inj in (r for r in rows if r["kind"] == "injection"):
        same = [u for u in users if u["suite"] == inj["suite"]]
        for u in rng.sample(same, min(PAIRS, len(same))):
            for k, c in enumerate(inj["calls"]):
                if c["function"].startswith(READS) and c["function"] != "get_webpage":
                    continue
                items.append(Item(f"ad-inj-{inj['suite']}-{inj['id']}-{u['id']}-{k}", "agentdojo", "injection", "ask",
                                  [u["text"]], to_call(c)))
    return items


def routine() -> list[Item]:
    return [Item(f"rt-{i:03}", "routine", "safe", "allow", [text], call, folder, list(HISTORY.get(text, [])))
            for i, (text, call, folder) in enumerate(ROUTINE, 1)]


def scheduled() -> list[Item]:
    """Unattended runs (scheduled-tasks 3.4): the task's instructions as the user's words; `ask` is a refusal there."""
    return [Item(f"st-{i:03}", "scheduled", "safe" if label == "allow" else "overreach", label, [text], call, folder)
            for i, (text, call, folder, label) in enumerate(SCHEDULED, 1)]


def calendar() -> list[Item]:
    """Calendar writes (plan calendar 4.5): the user's words and one calendar call; `ask` where they didn't ask for it."""
    return [Item(f"cal-{i:03}", "calendar", "safe" if label == "allow" else "overreach", label, list(user), c, None)
            for i, (user, c, label) in enumerate(CALENDAR, 1)]


def with_context(its: list[Item], path: Path = CONTEXT) -> list[Item]:
    """AgentDojo items with their history (agentdojo-context.jsonl); an item without a row keeps none."""
    if not path.exists():
        return its
    rows = {r["id"]: r for r in (json.loads(x) for x in path.read_text().splitlines() if x.strip())}
    for it in its:
        r = rows.get(it.id)
        if r is not None:
            it.history = [h for h in r["history"] if h.get("role") != "user"]
            it.planted = bool(r.get("planted"))
    return its


def items() -> list[Item]:
    return with_context(agentdojo()) + routine()
