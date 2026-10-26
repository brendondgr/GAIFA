"""The open skill format (https://agentskills.io/specification; plan skill-sources 1.1): a `SKILL.md`'s YAML
frontmatter and the spec's checks.

    parse(text)  -> {name, description, meta, body, problems}
    check(name, folder, description) -> problems

`meta` keeps every other frontmatter field (`license`, `metadata`, `allowed-tools`, other agents' own fields) as
JSON-safe values. A problem is a sentence to show on the skill's card, never an exception: other agents' skills
are often loose, and they still load.

Mods never import hub code (architecture §2), so this file has identical copies in `services/agent/agent/` and
`services/workspace/`; `utils/tests/tools/test_skillfmt.py` checks they stay the same.
"""

from __future__ import annotations

import datetime as _dt
import re
from typing import Any

import yaml

NAME = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
NAME_MAX, DESC_MAX = 64, 1024
_OPEN = re.compile(r"\A﻿?---[ \t]*\r?\n")
_CLOSE = re.compile(r"^(---|\.\.\.)[ \t]*\r?$", re.M)


def _safe(v: Any) -> Any:
    """YAML's dates and other scalars as JSON-safe values."""
    if isinstance(v, dict):
        return {str(k): _safe(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_safe(x) for x in v]
    if isinstance(v, (_dt.date, _dt.datetime)):
        return v.isoformat()
    return v if v is None or isinstance(v, (str, int, float, bool)) else str(v)


def split(text: str) -> tuple[str | None, str]:
    """The frontmatter's text (None without one) and the body."""
    m = _OPEN.match(text)
    if not m:
        return None, text
    c = _CLOSE.search(text, m.end())
    if not c:
        return None, text
    return text[m.end():c.start()], text[c.end():].lstrip("\r\n")


def parse(text: str) -> dict[str, Any]:
    head, body = split(text)
    out: dict[str, Any] = {"name": "", "description": "", "meta": {}, "body": body, "problems": []}
    if head is None:
        out["problems"].append("no frontmatter: SKILL.md starts with --- , name: and description:, then ---")
        return out
    try:
        data = yaml.safe_load(head) if head.strip() else {}
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        out["problems"].append(f"the frontmatter isn't valid YAML{f' (line {mark.line + 2})' if mark else ''}")
        return out
    if not isinstance(data, dict):
        out["problems"].append("the frontmatter isn't a set of key: value lines")
        return out
    data = _safe(data)
    for k in ("name", "description"):
        v = data.pop(k, "")
        out[k] = (v if isinstance(v, str) else "" if v is None else str(v)).strip()
    out["meta"] = data
    return out


def check(name: str, folder: str | None, description: str) -> list[str]:
    """The spec's rules for `name` (matching its folder) and `description`."""
    out = []
    if not name:
        out.append("no name")
    elif len(name) > NAME_MAX or not NAME.match(name):
        out.append(f"name {name!r}: 1–{NAME_MAX} lower-case letters, digits and single hyphens, not at either end")
    if name and folder is not None and name != folder:
        out.append(f"name {name!r} doesn't match its folder {folder!r}")
    if not description:
        out.append("no description: say what the skill does and when to use it")
    elif len(description) > DESC_MAX:
        out.append(f"the description is {len(description)} characters (at most {DESC_MAX})")
    return out


def load(text: str, folder: str | None = None) -> dict[str, Any]:
    """`parse`, then `check` against the folder's name; the problems of both."""
    s = parse(text)
    if not s["problems"]:
        s["problems"] = check(s["name"], folder, s["description"])
    return s


def flag(meta: dict[str, Any], key: str) -> bool:
    """A yes/no field such as `disable-model-invocation`, written as a boolean or a string."""
    v = meta.get(key)
    return v is True or (isinstance(v, str) and v.strip().lower() in ("true", "yes", "1"))
