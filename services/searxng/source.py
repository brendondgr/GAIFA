"""Which SearXNG search uses (plan capability-enablement 5.1): the user's own (found by detect) or GAIFA's own container
(managed.py, 5.2). Saved in `data/state/searxng/source.json` as `{"source": "yours" | "managed", "url": …}`; no file:
nothing chosen yet, and the mod uses what detect finds, as before.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

SOURCES = ("yours", "managed")


def state_dir() -> Path:
    # GAIFA's root: GAIFA_ROOT, else the folder this mod sits in (services/searxng → its root), never the current folder,
    # which a setup step runs in (the fresh-clone check found source.json written under services/searxng/data/)
    root = os.environ.get("GAIFA_ROOT") or str(Path(__file__).resolve().parents[2])
    return Path(root).resolve() / "data" / "state" / "searxng"


def load(d: Path | None = None) -> dict[str, Any] | None:
    f = (d or state_dir()) / "source.json"
    try:
        v = json.loads(f.read_text())
    except (OSError, ValueError):
        return None
    return v if isinstance(v, dict) and v.get("source") in SOURCES else None


def save(source: str, url: str | None, d: Path | None = None) -> dict[str, Any]:
    if source not in SOURCES:
        raise ValueError(f"source must be one of {', '.join(SOURCES)}")
    d = d or state_dir()
    d.mkdir(parents=True, exist_ok=True)
    v = {"source": source, "url": (url or "").rstrip("/") or None}
    tmp = d / ".source.json.tmp"
    tmp.write_text(json.dumps(v))
    tmp.replace(d / "source.json")
    return v
