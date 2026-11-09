"""What every chat knows without searching (plan structured-memory 3.3).

- **The profile** (in the system prompt): the user's current facts with their dates, preferences first (newest
  first, by when they began), then interests by when they were last said and a line of earlier interests, up to
  PROFILE_MAX characters (what doesn't fit comes in through recall);
  the active projects by name and one-line summary; and, for a chat working in workspace folders, the projects those
  folders are (by an anchor, or by the folder's name) with their current facts. It changes only when memory does,
  so a local server's prefix cache holds between turns. A project's own entity (plan projects 4.2: a `project`
  anchor) and what is under it are kept to that project's chats: in them its facts lead the profile (CHAT_MAX_PROJECT),
  elsewhere it is left off the "Projects:" line and out of recall.
- **Recall** (on each user message): `memory_search` on the message, the facts not already in the profile, stored on
  the user's event so the message is the same every time it is sent again.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from .model import norm
from .search import search
from .store import MemoryStore

PROFILE_MAX = 3000          # characters of the user's own facts (an import's instructions are many; memory-import 2.2)
PROJECTS_MAX = 12
CHAT_MAX = 900              # characters of the chat's projects' facts
CHAT_MAX_PROJECT = 1500     # … in a project chat, its project's (plan projects 4.2)
RECALL_MAX = 800            # characters recalled on a message
RECALL_FACTS = 8
INTEREST_DAYS = 90          # an interest not said this long is an earlier one (memory-auto-learning 3.2)
EARLIER_MAX = 5
MEANING_WAIT_S = 2.5        # recall doesn't hold a message up for a model load: names and words answer meanwhile


def _inside(a: str, b: str) -> bool:
    a, b = os.path.realpath(a), os.path.realpath(b)
    return a == b or a.startswith(b.rstrip("/") + "/")


def chat_projects(m: MemoryStore, folders: list[dict[str, Any]] | None, project: str | None = None) -> list[dict[str, Any]]:
    """The projects a chat's folders are: an anchor (workspace id, or a folder at or above it), or the same name; and the
    entity anchored to the chat's own project (`project`, plan projects 4.2), first. Another project's entity never."""
    from ..projects.memory import private
    hidden = private(m, project)
    out = []
    for e in m.entities("project"):
        anchors = m.anchors(e["id"])
        if project and any(a["kind"] == "project" and a["value"] == project for a in anchors):
            out.insert(0, e)
            continue
        if e["id"] in hidden or not folders:
            continue
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


def said_at(f: dict[str, Any]) -> float:
    """When the user last said a fact: its newest evidence's message time, else when it was saved."""
    ts = [float(e["ts"]) for e in f.get("evidence") or [] if isinstance(e, dict) and isinstance(e.get("ts"), (int, float))]
    return max(ts) if ts else float(f.get("recorded") or 0)


def begun(f: dict[str, Any]) -> float:
    """When a fact began: its `valid_from` (an imported entry's date), else when it was saved (memory-import 2.2)."""
    try:
        return time.mktime(time.strptime(f["valid_from"], "%Y-%m-%d")) if f.get("valid_from") else float(f.get("recorded") or 0)
    except ValueError:
        return float(f.get("recorded") or 0)


def _month(f: dict[str, Any]) -> str:
    return (f.get("valid_from") or time.strftime("%Y-%m-%d", time.localtime(f.get("recorded") or 0)))[:7]


def dated(f: dict[str, Any]) -> str:
    """A fact as the profile writes it, with its time (memory-auto-learning 3.2): "… (since 2026-11)", and for one
    that ended "… (2026-09 – 2026-11)"."""
    if f.get("valid_until") and not f.get("current", True):
        return f"{f['text']} ({_month(f)} – {f['valid_until'][:7]})"
    return f"{f['text']} (since {_month(f)})"


def build(m: MemoryStore, folders: list[dict[str, Any]] | None = None, interest_days: int = INTEREST_DAYS,
          project: str | None = None, user: bool = True, own_project: bool = True) -> tuple[str, set[str]]:
    """(the profile's text, the ids of the facts it shows). The user's facts carry their dates; preferences come
    first, newest first, then interests by when they were last said, then the rest, newest first; an interest not
    said for `interest_days`, or one that was replaced or ended this past year, goes on the "Earlier interests" line.
    `project`: the chat's project (plan projects 4.2), whose facts come first. A scheduled task's switches
    (scheduled-tasks 2.4): `user=False` leaves out the user's facts and the projects line, `own_project=False` the
    project's own memory."""
    from ..projects.memory import private
    shown: set[str] = set()
    parts = []
    keep_out: set[str] = set()
    if not own_project:
        project, keep_out = None, private(m, None)          # every project's memory kept out, its own included
    mine =[e for e in chat_projects(m, folders, project) if project and
            any(a["kind"] == "project" and a["value"] == project for a in m.anchors(e["id"]))]
    for e in mine:                                         # the project chat's own project leads
        facts, size = [], 0
        for f in m.facts_of(e["id"]):
            line = f"- {f['text']}"
            if size + len(line) > CHAT_MAX_PROJECT:
                break
            facts.append(line)
            size += len(line) + 1
            shown.add(f["id"])
        parts.append(f"This chat is in the project {e['name']} ({m.path(e)})" + (":\n" + "\n".join(facts) if facts else "."))
    stale = time.time() - interest_days * 86400
    now_, earlier = [], []
    for f in m.facts_of("user"):
        (earlier if f["kind"] == "interest" and said_at(f) < stale else now_).append(f)
    rank = {"preference": 0, "interest": 1}
    you = sorted(now_, key=lambda f: (rank.get(f["kind"], 2), -(said_at(f) if f["kind"] == "interest" else begun(f))))
    lines, size = [], 0
    for f in you:
        line = f"- {dated(f)}"
        if size + len(line) > PROFILE_MAX:
            break
        lines.append(line)
        size += len(line) + 1
        shown.add(f["id"])
    year = time.strftime("%Y-%m-%d", time.localtime(time.time() - 365 * 86400))
    ended = [f for f in m.facts_of("user", current=False) if f["kind"] == "interest" and not f["current"]
             and f["state"] == "retired" and (f["valid_until"] or "") >= year]
    earlier = sorted(earlier, key=lambda f: -said_at(f)) + sorted(ended, key=lambda f: f["valid_until"] or "", reverse=True)
    if earlier:
        lines.append("- Earlier interests: " + "; ".join(dated(f).removeprefix("The user ") for f in earlier[:EARLIER_MAX]))
        shown.update(f["id"] for f in earlier[:EARLIER_MAX])
    if not user:
        shown.difference_update(f["id"] for f in [*you, *earlier])
        lines = []
    if lines:
        parts.append("About the user:\n" + "\n".join(lines))
    hidden = private(m, project)
    projects = [e for e in m.entities("project") if not e["parent"] and e["id"] not in hidden][:PROJECTS_MAX] if user else []
    if projects:
        parts.append("Projects: " + "; ".join(e["name"] + (f" ({e['summary']})" if e["summary"] else "") for e in projects))
    for e in chat_projects(m, folders, project):
        if e in mine or e["id"] in keep_out:
            continue
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
    base = {"recall": True, "interest_days": INTEREST_DAYS}
    try:
        return {**base, **json.loads((data / "memory.json").read_text())}
    except (OSError, ValueError):
        return base


async def recall(m: MemoryStore, hub: Any, text: str, shown: set[str], project: str | None = None,
                 user: bool = True, own_project: bool = True) -> list[dict[str, Any]]:
    """The facts a message calls to mind, not already in the profile, best first; [] for a short or empty message.
    Facts about another project's entity are left out (plan projects 4.2; `project`: the chat's own). A scheduled
    task's switches (scheduled-tasks 2.4): `user=False` leaves out facts about the user, `own_project=False` the
    project's own."""
    from ..projects.memory import private
    if len((text or "").strip()) < 3:
        return []
    r = await search(m, hub, text, limit=RECALL_FACTS * 2, meaning_wait=MEANING_WAIT_S)
    hidden = private(m, project if own_project else None) | (set() if user else {"user"})
    out, size = [], 0
    for f in r["facts"]:
        if f["id"] in shown:
            continue
        if hidden and {row["entity"] for row in m._rows("SELECT entity FROM mem_fact_entities WHERE fact = ?", (f["id"],))} & hidden:
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

