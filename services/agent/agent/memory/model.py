"""What memory is made of (plan structured-memory 1.1).

An **entity** is something facts are about: the user (one, id `user`), a project, a person, a place, a tool, a
topic, an organization. It has a stable id, a name, aliases (every old name stays one, so a rename never loses
anything), anchors (a workspace folder or a git remote that identify a project) and a parent: entities form a tree,
and a path is the kind's folder and the names down to it (`projects/GAIFA`, `projects/GAIFA/agent`). There are no
other links between entities: this is not a graph.

A **fact** says one thing about one or more entities, in a sentence. It holds from `valid_from` until `valid_until`
(ISO dates, either may be empty), came from the user (`stated`), the agent's learning (`inferred`) or an import, and
is `proposed` (waiting for the user), `active`, `retired` (replaced, ended or let go) or `rejected`. A fact is never
overwritten: a new one replaces it (`replaces`/`replaced_by`) and the old one stays as history.
"""

from __future__ import annotations

import re
import time

KINDS = ("user", "project", "person", "place", "tool", "topic", "organization")
FOLDERS = {"user": "you", "project": "projects", "person": "people", "place": "places", "tool": "tools",
           "topic": "topics", "organization": "organizations"}
BY_FOLDER = {v: k for k, v in FOLDERS.items()}
FACT_KINDS = ("preference", "fact", "interest", "event", "procedure")   # interest: for now (memory-auto-learning 3.1)
FACT_STATES = ("proposed", "active", "retired", "rejected")
ENTITY_STATES = ("proposed", "active", "merged", "archived")
SOURCES = ("stated", "inferred", "imported")
USER = "user"
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class MemoryError(Exception):
    def __init__(self, status: int, code: str, detail: str, fix: str | None = None) -> None:
        super().__init__(detail)
        self.status, self.code, self.detail, self.fix = status, code, detail, fix


def norm(name: str) -> str:
    """A name as names are compared: lower case, words only ("AIHub" and "aihub", "GAIFA-hub" and "gaifa hub")."""
    return " ".join(re.findall(r"[^\W_]+", (name or "").lower()))


def today() -> str:
    return time.strftime("%Y-%m-%d")


def check_date(v: str | None, field: str) -> str | None:
    if v in (None, ""):
        return None
    if not isinstance(v, str) or not DATE.match(v):
        raise MemoryError(422, "bad_date", f"{field} must be a date like 2026-10-26")
    return v


def kind_of(word: str | None) -> str:
    """A kind from its name or its folder ("projects" → project); unknown → topic."""
    w = (word or "").strip().lower()
    return w if w in KINDS else BY_FOLDER.get(w, BY_FOLDER.get(w + "s", "topic"))
