"""The harness as versioned files (plan 22.1): the agent's instructions, which the learner improves.

Base, in git: `services/agent/harness/`
    systemprompt.md          the always-on prompt (was prompts.BASE)
    guardrails.md            standing rules, after the prompt (empty at first)
    hooks.toml               declarative hooks in the tool loop (agent/hooks.py; empty at first)
    tools/<tool>.md          notes appended to that tool's description
    skills/<name>/SKILL.md   on-demand procedures (frontmatter name, description)

Learned, not in git: `data/agent/harness/versions/<n>/` holds only the files version n changes, plus
`VERSION.json` {n, parent, created, adopted_by: auto|user|proposed, notes, gate, removed: [...]}; the
active number is in `data/agent/harness/current` (0 = the base). A version's tree is the base with
its chain of overlays applied, so a rollback is moving the pointer, and the base never changes.
"""

from __future__ import annotations

import difflib
import json
import re
import time
import tomllib
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parents[1] / "harness"
ALWAYS_ON = ("systemprompt.md", "guardrails.md")
ALWAYS_ON_MAX = 24_000             # characters: every one competes with the model's own budget (Harness²)
FILE = re.compile(r"^(systemprompt\.md|guardrails\.md|hooks\.toml|tools/[a-z0-9_]+\.md|skills/[a-z0-9][a-z0-9_-]{0,63}/SKILL\.md)$")


class HarnessError(Exception):
    pass


def _frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    meta = {}
    for line in text[3:end if end > 0 else 3].strip().splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()
    return meta


class Harness:
    def __init__(self, data: Path | str, base: Path | str = BASE_DIR) -> None:
        self.base = Path(base)
        self.root = Path(data) / "harness"
        self.versions_dir = self.root / "versions"

    # ---- versions -------------------------------------------------------------------------------

    def current(self) -> int:
        try:
            n = int((self.root / "current").read_text().strip() or 0)
        except (OSError, ValueError):
            return 0
        return n if n == 0 or (self.versions_dir / str(n)).is_dir() else 0

    def meta(self, n: int) -> dict[str, Any]:
        if n == 0:
            return {"n": 0, "parent": None, "created": None, "adopted_by": "base", "notes": "the base harness (in git)", "gate": None, "removed": []}
        f = self.versions_dir / str(n) / "VERSION.json"
        if not f.is_file():
            raise HarnessError(f"no harness version {n}")
        return json.loads(f.read_text())

    def versions(self) -> list[dict[str, Any]]:
        ns = sorted(int(p.name) for p in self.versions_dir.glob("*") if p.name.isdigit()) if self.versions_dir.is_dir() else []
        cur = self.current()
        out = [self.meta(0)] + [self.meta(n) for n in ns]
        for v in out:
            v["active"] = v["n"] == cur
        return out

    def chain(self, n: int) -> list[int]:
        out = []
        while n:
            out.append(n)
            n = self.meta(n).get("parent") or 0
        return list(reversed(out))

    def tree(self, n: int | None = None) -> dict[str, str]:
        """Every harness file of version n (default: the active one), base first, then its overlays."""
        n = self.current() if n is None else n
        out: dict[str, str] = {}
        for p in sorted(self.base.rglob("*")) if self.base.is_dir() else []:
            rel = p.relative_to(self.base).as_posix()
            if p.is_file() and FILE.match(rel):
                out[rel] = p.read_text()
        for v in self.chain(n):
            d = self.versions_dir / str(v)
            for rel in self.meta(v).get("removed") or []:
                out.pop(rel, None)
            for p in sorted(d.rglob("*")):
                rel = p.relative_to(d).as_posix()
                if p.is_file() and FILE.match(rel):
                    out[rel] = p.read_text()
        return out

    def create(self, files: dict[str, str], removed: list[str] | None = None, parent: int | None = None, notes: str = "",
               adopted_by: str = "auto", gate: dict[str, Any] | None = None, activate: bool = False,
               tools: set[str] | None = None) -> int:
        """A new version: `files` (changed or added), `removed`, on top of `parent` (default: the active one)."""
        parent = self.current() if parent is None else parent
        tree = {**{k: v for k, v in self.tree(parent).items() if k not in (removed or [])}, **files}
        bad = [rel for rel in [*files, *(removed or [])] if not FILE.match(rel)]
        problems = ([f"{r}: not a harness file" for r in bad]) + validate(tree, tools)
        if problems:
            raise HarnessError("; ".join(problems[:6]))
        self.versions_dir.mkdir(parents=True, exist_ok=True)
        n = max([0, *(int(p.name) for p in self.versions_dir.glob("*") if p.name.isdigit())]) + 1
        d = self.versions_dir / str(n)
        for rel, text in files.items():
            (d / rel).parent.mkdir(parents=True, exist_ok=True)
            (d / rel).write_text(text)
        meta = {"n": n, "parent": parent, "created": time.time(), "adopted_by": adopted_by, "notes": notes, "gate": gate,
                "removed": list(removed or []), "files": sorted(files)}
        (d / "VERSION.json").write_text(json.dumps(meta, indent=1))
        if activate:
            self.activate(n)
        return n

    def activate(self, n: int) -> None:
        if n:
            self.meta(n)
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.root / "current.part"
        tmp.write_text(str(n))
        tmp.replace(self.root / "current")

    def set_meta(self, n: int, **fields: Any) -> None:
        m = self.meta(n)
        m.update(fields)
        (self.versions_dir / str(n) / "VERSION.json").write_text(json.dumps(m, indent=1))

    def diff(self, a: int, b: int) -> str:
        ta, tb = self.tree(a), self.tree(b)
        out = []
        for rel in sorted(set(ta) | set(tb)):
            if ta.get(rel) != tb.get(rel):
                out += difflib.unified_diff((ta.get(rel) or "").splitlines(True), (tb.get(rel) or "").splitlines(True),
                                            f"v{a}/{rel}", f"v{b}/{rel}")
        return "".join(out)


def validate(tree: dict[str, str], tools: set[str] | None = None) -> list[str]:
    """Problems that make a harness unusable (the learner's proposals are checked before any replay)."""
    from . import hooks

    out = []
    always = sum(len(tree.get(f) or "") for f in ALWAYS_ON)
    if always > ALWAYS_ON_MAX:
        out.append(f"always-on text is {always} characters (at most {ALWAYS_ON_MAX}): move detail into a skill or a tool note")
    if not (tree.get("systemprompt.md") or "").strip():
        out.append("systemprompt.md is empty")
    for f in ALWAYS_ON:
        if "{{" in (tree.get(f) or "") or "{%" in (tree.get(f) or ""):
            out.append(f"{f}: template braces ({{{{ or {{%) aren't allowed")
    for rel, text in tree.items():
        if rel.startswith("skills/"):
            meta = _frontmatter(text)
            name = rel.split("/")[1]
            if meta.get("name") != name or not meta.get("description"):
                out.append(f"{rel}: frontmatter needs name: {name} and a description")
        if rel.startswith("tools/") and tools is not None and rel[6:-3] not in tools:
            out.append(f"{rel}: there is no tool {rel[6:-3]!r}")
    if (tree.get("hooks.toml") or "").strip():
        try:
            out += hooks.problems(tomllib.loads(tree["hooks.toml"]), tools)
        except tomllib.TOMLDecodeError as e:
            out.append(f"hooks.toml: {e}")
    return out


def skills(tree: dict[str, str]) -> list[dict[str, str]]:
    return [{"name": rel.split("/")[1], "description": _frontmatter(t).get("description", ""), "source": "harness",
             "id": f"user/{rel.split('/')[1]}"} for rel, t in sorted(tree.items()) if rel.startswith("skills/")]


def skill_body(tree: dict[str, str], name: str) -> str | None:
    t = tree.get(f"skills/{name}/SKILL.md")
    if t is None:
        return None
    end = t.find("\n---", 3) if t.startswith("---") else -1
    return t[end + 4:].lstrip("\n") if end > 0 else t
