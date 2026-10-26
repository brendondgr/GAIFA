"""What every chat knows without searching (plan structured-memory 3.3).

- **The profile** (in the system prompt): the user's current facts, preferences first, up to PROFILE_MAX characters;
  the active projects by name and one-line summary; and, for a chat working in workspace folders, the projects those
  folders are (by an anchor, or by the folder's name) with their current facts. It changes only when memory does,
  so a local server's prefix cache holds between turns.
- **Recall** (on each user message): `memory_search` on the message, the facts not already in the profile, stored on
  the user's event so the message is the same every time it is sent again.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .model import norm
from .search import search
from .store import MemoryStore

PROFILE_MAX = 1500          # characters of the user's own facts
PROJECTS_MAX = 12
CHAT_MAX = 900              # characters of the chat's projects' facts
RECALL_MAX = 800            # characters recalled on a message
RECALL_FACTS = 8
MEANING_WAIT_S = 2.5        # recall doesn't hold a message up for a model load: names and words answer meanwhile


def _inside(a: str, b: str) -> bool:
    a, b = os.path.realpath(a), os.path.realpath(b)
    return a == b or a.startswith(b.rstrip("/") + "/")


def chat_projects(m: MemoryStore, folders: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """The projects a chat's folders are: an anchor (workspace id, or a folder at or above it), or the same name."""
    if not folders:
        return []
    out = []
    for e in m.entities("project"):
        anchors = m.anchors(e["id"])
        names = {e["norm"], *(norm(a) for a in m.aliases(e["id"]))}
        for f in folders:
            path, fid = str(f.get("path") or ""), str(f.get("id") or "")
            hit = any((a["kind"] == "workspace" and a["value"] == fid) or
                      (a["kind"] == "folder" and path and (_inside(path, a["value"]) or _inside(a["value"], path)))
                      for a in anchors)
            if hit or norm(f.get("name") or os.path.basename(path)) in names:
                out.append(e)
                break
    return out


def build(m: MemoryStore, folders: list[dict[str, Any]] | None = None) -> tuple[str, set[str]]:
    """(the profile's text, the ids of the facts it shows)."""
    shown: set[str] = set()
    parts = []
    you = sorted(m.facts_of("user"), key=lambda f: (f["kind"] != "preference", -(f["updated"] or 0)))
    lines, size = [], 0
    for f in you:
        line = f"- {f['text']}"
        if size + len(line) > PROFILE_MAX:
            break
        lines.append(line)
        size += len(line) + 1
        shown.add(f["id"])
    if lines:
        parts.append("About the user:\n" + "\n".join(lines))
    projects = [e for e in m.entities("project") if not e["parent"]][:PROJECTS_MAX]
    if projects:
        parts.append("Projects: " + "; ".join(e["name"] + (f" ({e['summary']})" if e["summary"] else "") for e in projects))
    for e in chat_projects(m, folders):
        facts, size = [], 0
        for f in m.facts_of(e["id"]):
            line = f"- {f['text']}"
            if size + len(line) > CHAT_MAX:
                break
            facts.append(line)
            size += len(line) + 1
            shown.add(f["id"])
        parts.append(f"This chat works in {e['name']} ({m.path(e)})" + (":\n" + "\n".join(facts) if facts else "."))
    return "\n".join(parts), shown


def settings(data: Path) -> dict[str, Any]:
    try:
        return {"recall": True, **json.loads((data / "memory.json").read_text())}
    except (OSError, ValueError):
        return {"recall": True}


async def recall(m: MemoryStore, hub: Any, text: str, shown: set[str]) -> list[dict[str, Any]]:
    """The facts a message calls to mind, not already in the profile, best first; [] for a short or empty message."""
    if len((text or "").strip()) < 3:
        return []
    r = await search(m, hub, text, limit=RECALL_FACTS * 2, meaning_wait=MEANING_WAIT_S)
    out, size = [], 0
    for f in r["facts"]:
        if f["id"] in shown:
            continue
        about = [p for p in f["about"] if p != "you"]
        line = f["text"] + (f" ({', '.join(about)})" if about else "")
        if size + len(line) > RECALL_MAX or len(out) >= RECALL_FACTS:
            break
        out.append({"id": f["id"], "text": f["text"], "about": about})
        size += len(line)
    return out


def block(recalled: list[dict[str, Any]]) -> str:
    """How recalled facts follow the user's words in their message."""
    if not recalled:
        return ""
    rows = "\n".join(f"- {r['text']}" + (f" ({', '.join(r['about'])})" if r.get("about") else "") for r in recalled)
    return f"<memory note=\"what you remembered when this message came; not the user's words\">\n{rows}\n</memory>"

