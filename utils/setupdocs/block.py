"""The `aihub-setup` block, version 2 (plan 23.7): what `aihub setup` reads from a setup doc.

Every key past `id` and `title` is optional, so a doc without them still parses; the wizard lists
only docs with a `summary`. Unknown keys are errors, at the top and inside `[[steps]]` and `[[suggest]]`.
"""

from __future__ import annotations

import posixpath
from dataclasses import dataclass, field
from typing import Any

TOP = {"id", "title", "models", "scan", "summary", "gpu", "disk_gb", "needs", "after", "check", "steps", "suggest"}
STEP = {"run", "what", "ask"}
SUGGEST = {"name", "repo", "revision", "files", "dest", "kind", "op", "body", "size_gb", "good_for", "licence", "required", "gated"}


@dataclass
class Step:
    run: str                        # bash, in the mod's folder
    what: str                       # what it does, how big, how long
    ask: str = ""                   # a yes/no question first (a licence); empty: no question


@dataclass
class Suggest:
    name: str
    size_gb: float
    good_for: str
    repo: str = ""                  # a Hugging Face repo…
    revision: str = ""
    files: list[str] = field(default_factory=list)   # empty: the whole repo
    dest: str = ""                  # "hf-cache", or a folder under data/models/
    kind: str = "other"             # the registry kind it's registered as (llm, tts, image, …)
    op: str = ""                    # …or a mod route that downloads and registers it ("POST /v1/load")
    body: dict[str, Any] = field(default_factory=dict)
    licence: str = ""
    required: bool = False          # the engine can't run without it
    gated: bool = False             # accept the repo's terms on Hugging Face first


@dataclass
class Setup:
    summary: str = ""
    gpu: bool | None = None
    disk_gb: float | None = None
    needs: list[str] = field(default_factory=list)
    after: list[str] = field(default_factory=list)
    check: str = ""
    steps: list[Step] = field(default_factory=list)
    suggest: list[Suggest] = field(default_factory=list)


def _strs(v: Any) -> bool:
    return isinstance(v, list) and all(isinstance(s, str) and s.strip() for s in v)


def _num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0


def _step(i: int, d: Any) -> tuple[Step | None, str | None]:
    where = f"steps[{i}]"
    if not isinstance(d, dict):
        return None, f"{where} must be a table ([[steps]])"
    unknown = sorted(set(d) - STEP)
    if unknown:
        return None, f"{where}: unknown key(s) {', '.join(unknown)} (allowed: {', '.join(sorted(STEP))})"
    for key in ("run", "what"):
        if not isinstance(d.get(key), str) or not d[key].strip():
            return None, f"{where}: `{key}` must be a non-empty string"
    if not isinstance(d.get("ask", ""), str):
        return None, f"{where}: `ask` must be a string"
    return Step(run=d["run"].strip(), what=d["what"].strip(), ask=d.get("ask", "").strip()), None


def _suggest(i: int, d: Any) -> tuple[Suggest | None, str | None]:
    where = f"suggest[{i}]"
    if not isinstance(d, dict):
        return None, f"{where} must be a table ([[suggest]])"
    unknown = sorted(set(d) - SUGGEST)
    if unknown:
        return None, f"{where}: unknown key(s) {', '.join(unknown)} (allowed: {', '.join(sorted(SUGGEST))})"
    for key in ("name", "good_for"):
        if not isinstance(d.get(key), str) or not d[key].strip():
            return None, f"{where}: `{key}` must be a non-empty string"
    if not _num(d.get("size_gb")):
        return None, f"{where}: `size_gb` must be a number of GB (0 or more)"
    repo, op = d.get("repo", ""), d.get("op", "")
    if not isinstance(repo, str) or not isinstance(op, str) or bool(repo.strip()) == bool(op.strip()):
        return None, f"{where}: give either `repo` (a Hugging Face repo) or `op` (a mod route), not both or neither"
    if repo:
        if repo.count("/") != 1 or " " in repo:
            return None, f"{where}: `repo` must look like org/name"
        dest = d.get("dest", "")
        if not isinstance(dest, str) or not dest.strip():
            return None, f"{where}: a `repo` needs `dest` (\"hf-cache\", or a folder under data/models/)"
        norm = posixpath.normpath(dest.strip())
        if norm.startswith(("/", "..")) or norm == ".":
            return None, f"{where}: `dest` must be a folder inside data/models/"
        if "op" in d or "body" in d:
            return None, f"{where}: `body` goes with `op`, not `repo`"
        if not isinstance(d.get("kind", "other"), str) or not d.get("kind", "other").strip():
            return None, f"{where}: `kind` must be a registry kind (llm, tts, image, …)"
    else:
        if len(op.split()) != 2 or op.split()[0] not in ("GET", "POST", "PUT") or not op.split()[1].startswith("/"):
            return None, f"{where}: `op` must look like \"POST /v1/load\""
        if not isinstance(d.get("body", {}), dict):
            return None, f"{where}: `body` must be a table"
        if any(k in d for k in ("dest", "files", "revision", "kind")):
            return None, f"{where}: `dest`, `files`, `revision` and `kind` go with `repo`, not `op` (the mod registers what it downloads)"
    if not _strs(d.get("files", [])) and d.get("files", []) != []:
        return None, f"{where}: `files` must be a list of file names"
    for key in ("revision", "licence"):
        if not isinstance(d.get(key, ""), str):
            return None, f"{where}: `{key}` must be a string"
    for key in ("required", "gated"):
        if not isinstance(d.get(key, False), bool):
            return None, f"{where}: `{key}` must be true or false"
    return Suggest(name=d["name"].strip(), size_gb=float(d["size_gb"]), good_for=d["good_for"].strip(),
                   repo=repo.strip(), revision=d.get("revision", "").strip(), files=list(d.get("files", [])),
                   dest=posixpath.normpath(d["dest"].strip()) if repo else "", kind=d.get("kind", "other").strip(), op=op.strip(), body=dict(d.get("body", {})),
                   licence=d.get("licence", "").strip(), required=d.get("required", False), gated=d.get("gated", False)), None


def read(data: dict[str, Any]) -> tuple[Setup | None, str | None]:
    """The version-2 keys of an already-parsed block → (Setup, None) or (None, problem)."""
    out = Setup()
    if "summary" in data:
        if not isinstance(data["summary"], str) or not data["summary"].strip():
            return None, "`summary` must be a non-empty string (one line: what the mod gives you)"
        out.summary = data["summary"].strip()
    if "gpu" in data:
        if not isinstance(data["gpu"], bool):
            return None, "`gpu` must be true or false"
        out.gpu = data["gpu"]
    if "disk_gb" in data:
        if not _num(data["disk_gb"]):
            return None, "`disk_gb` must be a number of GB (0 or more)"
        out.disk_gb = float(data["disk_gb"])
    for key in ("needs", "after"):
        if key in data:
            if not _strs(data[key]):
                return None, f"`{key}` must be a list of strings"
            setattr(out, key, [s.strip() for s in data[key]])
    if "check" in data:
        if not isinstance(data["check"], str) or not data["check"].strip():
            return None, "`check` must be a non-empty command"
        out.check = data["check"].strip()
    for key, fn, into in (("steps", _step, out.steps), ("suggest", _suggest, out.suggest)):
        v = data.get(key, [])
        if not isinstance(v, list):
            return None, f"`{key}` must be an array of tables ([[{key}]])"
        for i, d in enumerate(v):
            item, problem = fn(i, d)
            if problem:
                return None, problem
            into.append(item)
    return out, None
