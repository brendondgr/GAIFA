"""Once (plan structured-memory 1.3): what memory held before becomes facts.

- Each active `agent`-scope preference (what `remember` saved since plan 21.4) becomes a fact about the user, with
  the preference's source, and the preference is retired with a note pointing at the fact.
- Each line of `data/agent/memory/*.md` (plan 14.9) becomes an imported fact; a topic file's name becomes a topic
  the fact is also about. The files stay where they are.

Preferences are looked for at every start (each one moved is retired, so none comes twice); the files once, with a
marker, `data/agent/memory/.structured`.
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

from .model import MemoryError
from .store import MemoryStore

MARK = ".structured"


async def run(memory: MemoryStore, hub: Any, data: Path) -> int:
    mem = data / "memory"
    mark = mem / MARK
    if hub is None:
        return 0
    n = 0
    for p in await hub.prefs(scope="agent", state="active"):
        text = p["value"] if isinstance(p["value"], str) else str(p["value"])
        try:
            f = memory.add_fact(text, kind="preference", source="stated" if p.get("source") == "stated" else "imported",
                                evidence=[{"kind": "preference", "ref": p["id"]}], by="import")
        except MemoryError:
            continue
        await hub.update_pref(p["id"], {"state": "retired", "note": f"moved to memory: {f['id']}"})
        n += 1
    if mark.exists():
        return n
    for f in sorted(mem.glob("*.md")) if mem.is_dir() else []:
        topic = None if f.name == "MEMORY.md" else f.stem.replace("-", " ")
        for line in f.read_text().splitlines():
            text = re.sub(r"\s*\(\d{4}-\d{2}-\d{2}\)\s*$", "", line.lstrip("-* ").strip())
            if not text or text.startswith("#") or (text.startswith("[") and "](" in text):   # headings, index lines
                continue
            try:
                memory.add_fact(text, about=["you", *([{"name": topic, "kind": "topic"}] if topic else [])],
                                source="imported", evidence=[{"kind": "memory file", "ref": f.name}], by="import")
                n += 1
            except MemoryError:
                continue
    if mem.is_dir():                                    # no folder: nothing to import, and nothing written
        mark.write_text(time.strftime("%Y-%m-%d %H:%M"))
    return n
