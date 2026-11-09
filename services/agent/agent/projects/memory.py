"""A project's memory (plan projects 4.2): an entity of kind `project` in the structured memory, anchored to the
project (`{kind: "project", value: <pid>}`), made (or adopted, by name) when the project is.

- Renaming the project renames the entity, so the old name stays an alias.
- Its facts, and its children's, are kept to the project's own chats: other chats' profiles leave it off the
  "Projects:" line and recall leaves out its facts (memory/profile.py, `private`); in its chats they lead the profile.
- The learner is told when a chat is in a project, so facts about the work are filed under it (memory/learn.py).
- Deleting the project removes the anchor; the entity and its facts stay in Memory, where they can be deleted.
"""

from __future__ import annotations

import logging
from typing import Any

from ..memory.model import MemoryError

log = logging.getLogger("agent.projects")
ANCHOR = "project"


def entity_of(m: Any, pid: str) -> dict[str, Any] | None:
    """The project's entity, by its anchor."""
    r = m._row("SELECT entity FROM mem_anchors WHERE kind = ? AND value = ?", (ANCHOR, pid))
    e = m.entity_row(r["entity"]) if r else None
    return e if e and e["state"] == "active" else None


def private(m: Any, but: str | None = None) -> set[str]:
    """The entities kept to their project's chats: those with a project anchor (but the one for project `but`) and
    everything under them."""
    rows = m._rows("SELECT entity, value FROM mem_anchors WHERE kind = ?", (ANCHOR,))
    out = {r["entity"] for r in rows if r["value"] != but}
    if not out:
        return out
    kids = m._rows("SELECT id, parent FROM mem_entities WHERE parent IS NOT NULL", ())
    grew = True
    while grew:
        grew = False
        for k in kids:
            if k["parent"] in out and k["id"] not in out:
                out.add(k["id"])
                grew = True
    return out


async def created(agent: Any, p: dict[str, Any]) -> None:
    """Make the project's entity, or adopt the project entry of that name memory already has."""
    m = agent.memory
    e = entity_of(m, p["id"])
    if e is None:
        same = m.resolve(p["name"], "project")
        anchor = [{"kind": ANCHOR, "value": p["id"]}]
        if same is not None and same["kind"] == "project":
            m.update_entity(same["id"], anchors_add=anchor, by="agent")
            e = same
        else:
            name = p["name"] if same is None else f"{p['name']} (project)"
            try:
                e = m.create_entity("project", name, summary=(p.get("description") or "")[:300], anchors=anchor, by="agent")
            except MemoryError as err:
                log.info("project %s's memory entity: %s", p["id"], err.detail)
                return
    agent.projects.update(p["id"], memory_entity=e["id"])


async def changed(agent: Any, old: dict[str, Any], new: dict[str, Any]) -> None:
    """A rename renames the entity (the old name stays an alias)."""
    if old["name"] == new["name"]:
        return
    e = entity_of(agent.memory, new["id"])
    if e is None:
        return await created(agent, new)
    try:
        agent.memory.update_entity(e["id"], name=new["name"], by="agent")
    except MemoryError as err:                       # another entry has that name: the entity keeps its own
        log.info("renaming project %s's memory entity: %s", new["id"], err.detail)


async def forget_anchor(agent: Any, p: dict[str, Any]) -> str:
    """When the project is deleted: its entity loses the project anchor and stays, with its facts."""
    e = entity_of(agent.memory, p["id"])
    if e is None:
        return "none"
    agent.memory.update_entity(e["id"], anchors_remove=[{"kind": ANCHOR, "value": p["id"]}], by="agent")
    return e["id"]


def facts(agent: Any, pid: str) -> dict[str, Any]:
    """The project's entity and its facts (current ones and those waiting for review), in the memory routes' shape."""
    m = agent.memory
    e = entity_of(m, pid)
    if e is None:
        return {"entity": None, "facts": []}
    rows = [f for f in m.facts(entity=e["id"], limit=500) if f["current"] or f["state"] == "proposed"]
    return {"entity": {**m.public(e), "path": m.path(e)}, "facts": rows}
