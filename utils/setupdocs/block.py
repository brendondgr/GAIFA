"""The `aihub-setup` block, version 2 (plan 23.7): what `aihub setup` reads from a setup doc.

Every key past `id` and `title` is optional, so a doc without them still parses; the wizard lists
only docs with a `summary`. Unknown keys are errors, at the top and inside `[[steps]]` and `[[suggest]]`.
"""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass, field
from typing import Any

TOP = {"id", "title", "models", "scan", "summary", "gpu", "disk_gb", "images", "needs", "after", "check", "steps", "suggest", "config"}
CONFIG = {"key", "text", "choices", "required", "restart"}
CONFIG_KEY = re.compile(r"^(services\.[a-z][a-z0-9-]{1,31}\.env\.[A-Z][A-Z0-9_]*|agent\.judge\.model)$")
STEP = {"run", "what", "ask", "interactive", "skip_if", "optional"}
SUGGEST = {"name", "repo", "revision", "files", "dest", "kind", "op", "body", "size_gb", "good_for", "licence", "required", "gated", "next", "start_op", "start_body"}


@dataclass
class Step:
    run: str                        # bash, in the mod's folder
    what: str                       # what it does, how big, how long
    ask: str = ""                   # a yes/no question first (a licence); empty: no question
    interactive: bool = False       # it prompts (a login): under --json the person runs it, then the run resumes
    skip_if: str = ""               # a command: exit 0 means there's nothing to do (logged in already), so it's done
    optional: bool = False          # with an `ask`: a "no" skips only this step, not the whole setup


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
    next: str = ""                  # what the person still has to do once it's chosen (joins the report)
    start_op: str = ""              # a mod route run after the download, such as launching it ("POST /api/instances")
    start_body: dict[str, Any] = field(default_factory=dict)


@dataclass
class Config:
    key: str                        # services.<id>.env.<VAR>, or agent.judge.model, in config.toml
    text: str                       # the question
    choices: str | list[str] = "relay-models"   # the relay's models once it runs, "folder" (an absolute path outside AIHub), or a list
    required: bool = False          # no answer stops the run; else it's left for later (the report says so)
    restart: str = ""               # a mod id (or "hub") restarted once it's set


@dataclass
class Setup:
    summary: str = ""
    gpu: bool | None = None
    disk_gb: float | None = None                     # the environment, without its container images
    images: dict[str, float] = field(default_factory=dict)   # images it pulls → GB, counted once across setups
    needs: list[str] = field(default_factory=list)
    after: list[str] = field(default_factory=list)
    check: str = ""
    steps: list[Step] = field(default_factory=list)
    suggest: list[Suggest] = field(default_factory=list)
    config: list[Config] = field(default_factory=list)   # values asked after install (choices come from it)


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
    for key in ("interactive", "optional"):
        if not isinstance(d.get(key, False), bool):
            return None, f"{where}: `{key}` must be true or false"
    if not isinstance(d.get("skip_if", ""), str):
        return None, f"{where}: `skip_if` must be a command"
    if d.get("optional") and not d.get("ask"):
        return None, f"{where}: an `optional` step needs an `ask` (its question)"
    return Step(run=d["run"].strip(), what=d["what"].strip(), ask=d.get("ask", "").strip(), interactive=d.get("interactive", False),
                skip_if=d.get("skip_if", "").strip(), optional=d.get("optional", False)), None


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
    for key in ("revision", "licence", "next"):
        if not isinstance(d.get(key, ""), str):
            return None, f"{where}: `{key}` must be a string"
    so = d.get("start_op", "")
    if so and (not isinstance(so, str) or len(so.split()) != 2 or so.split()[0] not in ("POST", "PUT") or not so.split()[1].startswith("/")):
        return None, f"{where}: `start_op` must look like \"POST /api/instances\""
    if not isinstance(d.get("start_body", {}), dict) or (d.get("start_body") and not so):
        return None, f"{where}: `start_body` is a table, and needs `start_op`"
    for key in ("required", "gated"):
        if not isinstance(d.get(key, False), bool):
            return None, f"{where}: `{key}` must be true or false"
    return Suggest(name=d["name"].strip(), size_gb=float(d["size_gb"]), good_for=d["good_for"].strip(),
                   repo=repo.strip(), revision=d.get("revision", "").strip(), files=list(d.get("files", [])),
                   dest=posixpath.normpath(d["dest"].strip()) if repo else "", kind=d.get("kind", "other").strip(), op=op.strip(), body=dict(d.get("body", {})),
                   licence=d.get("licence", "").strip(), required=d.get("required", False), gated=d.get("gated", False),
                   next=d.get("next", "").strip(), start_op=so.strip() if so else "", start_body=dict(d.get("start_body", {}))), None


def _config(i: int, d: Any) -> tuple[Config | None, str | None]:
    where = f"config[{i}]"
    if not isinstance(d, dict):
        return None, f"{where} must be a table ([[config]])"
    unknown = sorted(set(d) - CONFIG)
    if unknown:
        return None, f"{where}: unknown key(s) {', '.join(unknown)} (allowed: {', '.join(sorted(CONFIG))})"
    if not isinstance(d.get("key"), str) or not CONFIG_KEY.match(d["key"]):
        return None, f"{where}: `key` must be services.<id>.env.<VAR> or agent.judge.model"
    if not isinstance(d.get("text"), str) or not d["text"].strip():
        return None, f"{where}: `text` must be a non-empty question"
    choices = d.get("choices", "relay-models")
    if not (choices in ("relay-models", "folder") or _strs(choices)):
        return None, f"{where}: `choices` must be \"relay-models\", \"folder\" or a list of strings"
    if not isinstance(d.get("required", False), bool) or not isinstance(d.get("restart", ""), str):
        return None, f"{where}: `required` is true or false, `restart` a mod id or \"hub\""
    return Config(key=d["key"], text=d["text"].strip(), choices=choices, required=d.get("required", False), restart=d.get("restart", "").strip()), None


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
    if "images" in data:
        im = data["images"]
        if not isinstance(im, dict) or not all(isinstance(k, str) and k.strip() and _num(v) for k, v in im.items()):
            return None, "`images` must be a table of image name = GB"
        out.images = {k.strip(): float(v) for k, v in im.items()}
    for key in ("needs", "after"):
        if key in data:
            if not _strs(data[key]):
                return None, f"`{key}` must be a list of strings"
            setattr(out, key, [s.strip() for s in data[key]])
    if "check" in data:
        if not isinstance(data["check"], str) or not data["check"].strip():
            return None, "`check` must be a non-empty command"
        out.check = data["check"].strip()
    for key, fn, into in (("steps", _step, out.steps), ("suggest", _suggest, out.suggest), ("config", _config, out.config)):
        v = data.get(key, [])
        if not isinstance(v, list):
            return None, f"`{key}` must be an array of tables ([[{key}]])"
        for i, d in enumerate(v):
            item, problem = fn(i, d)
            if problem:
                return None, problem
            into.append(item)
    return out, None
