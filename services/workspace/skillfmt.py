"""The open skill format (https://agentskills.io/specification; plan skill-sources 1.1): a `SKILL.md`'s YAML
frontmatter and the spec's checks.

    parse(text)  -> {name, description, meta, body, problems}
    check(name, folder, description) -> problems
    files(folder) -> [{path, size}]        a skill's other files (skill-sources 1.2)
    read_file(folder, path) -> text        one of them; SkillFileError when it can't be read

`meta` keeps every other frontmatter field (`license`, `metadata`, `allowed-tools`, other agents' own fields) as
JSON-safe values. A problem is a sentence to show on the skill's card, never an exception: other agents' skills
are often loose, and they still load.

Mods never import hub code (architecture §2), so this file has identical copies in `services/agent/agent/` and
`services/workspace/`; `utils/tests/tools/test_skillfmt.py` checks they stay the same.
"""

from __future__ import annotations

import datetime as _dt
import re
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

NAME = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
NAME_MAX, DESC_MAX = 64, 1024
FILE_MAX = 256 * 1024          # bytes: a skill's file read whole
FILES_MAX = 100                # files listed per skill
_OPEN = re.compile(r"\A\ufeff?---[ \t]*\r?\n")
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


class SkillFileError(Exception):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code, self.detail = code, detail


def _inside(folder: Path, p: Path) -> bool:
    try:
        return p.resolve().is_relative_to(folder.resolve())
    except OSError:
        return False


def files(folder: Path) -> list[dict[str, Any]]:
    """A skill folder's files other than SKILL.md, by path: no hidden ones, none through a symlink that leads out."""
    out: list[dict[str, Any]] = []
    for p in sorted(folder.rglob("*")):
        rel = p.relative_to(folder)
        if rel.as_posix() == "SKILL.md" or any(part.startswith(".") for part in rel.parts):
            continue
        if p.is_file() and _inside(folder, p):
            out.append({"path": rel.as_posix(), "size": p.stat().st_size})
            if len(out) >= FILES_MAX:
                break
    return out


def read_file(folder: Path, path: str) -> str:
    """One of a skill's files as text: inside the folder (no `..`, no symlink out), not hidden, at most FILE_MAX, UTF-8."""
    rel = PurePosixPath(path.strip())
    if not path.strip() or rel.is_absolute() or any(part in ("..", "") or part.startswith(".") for part in rel.parts):
        raise SkillFileError("not_found", f"no file {path!r} in this skill")
    p = folder / rel
    if not _inside(folder, p) or not p.is_file():
        raise SkillFileError("not_found", f"no file {path!r} in this skill")
    if p.stat().st_size > FILE_MAX:
        raise SkillFileError("too_big", f"{path} is {p.stat().st_size // 1024} KB (at most {FILE_MAX // 1024} KB)")
    data = p.read_bytes()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = None
    if text is None or "\x00" in text:
        raise SkillFileError("binary", f"{path} isn't a text file")
    return text


def files_note(sid: str, listed: list[dict[str, Any]]) -> str:
    """The line after a skill's body that names its other files, for the model."""
    if not listed:
        return ""
    rows = "\n".join(f"- {f['path']} ({max(1, round(f['size'] / 1024))} KB)" for f in listed)
    return f"\n\n---\nOther files in this skill (read one with read_skill('{sid}/<path>')):\n{rows}"
