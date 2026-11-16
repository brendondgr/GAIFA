"""The `gaifa-setup` block, versions 2 and 3 (plans 23.7, 38.1): what `gaifa setup` reads from a setup doc.

Every key past `id` and `title` is optional, so a doc without them still parses; the wizard lists
only docs with a `summary`. Unknown keys are errors, at the top and inside `[[steps]]` and `[[suggest]]`.

Version 3 adds `[[variants]]`, one per accelerator the setup can run on (`accel`, `os`, `tested`, `env`,
and optionally its own `steps`, `check` and `smoke`), and `smoke`: a command that does real work, run
by `gaifa setup --smoke` and the field test. A block without variants has one: `cpu` when `gpu = false`,
`rocm` on Linux when `gpu = true` (what the version-2 docs were written on).
"""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass, field
from typing import Any

TOP = {"id", "title", "models", "scan", "summary", "gpu", "disk_gb", "images", "needs", "after", "check", "steps", "suggest", "config",
       "variants", "smoke", "recommended", "choose", "find"}
VARIANT = {"accel", "os", "tested", "env", "steps", "check", "smoke", "note", "needs"}
ACCELS = ("rocm", "cuda", "xpu", "mps", "vulkan", "cpu")        # utils/hardware ACCELS, in the order they're tried
OSES = ("linux", "wsl", "darwin")
CONFIG = {"key", "text", "choices", "required", "restart", "when", "secret"}
CHOOSE = {"id", "text", "default", "options"}
FIND = {"label", "url", "note"}
OPTION = {"value", "label", "adds"}
CONFIG_KEY = re.compile(r"^(services\.[a-z][a-z0-9-]{1,31}\.env\.[A-Z][A-Z0-9_]*|agent\.judge\.model)$")
STEP = {"run", "what", "ask", "interactive", "skip_if", "optional", "next", "ask_if"}
SUGGEST = {"name", "repo", "revision", "files", "dest", "kind", "op", "body", "size_gb", "good_for", "licence", "required", "gated", "next", "start_op", "start_body", "skip_if"}


@dataclass
class Step:
    run: str                        # bash, in the mod's folder
    what: str                       # what it does, how big, how long
    ask: str = ""                   # a yes/no question first (a licence); empty: no question
    interactive: bool = False       # it prompts (a login): under --json the person runs it, then the run resumes
    skip_if: str = ""               # a command: exit 0 means there's nothing to do (logged in already), so it's done
    optional: bool = False          # with an `ask`: a "no" skips only this step, not the whole setup
    next: str = ""                  # what the person still has to do once it has run (joins the report)
    ask_if: str = ""                # capability-enablement 5.3: a command run while planning; exit 0: the step (and its
    #                                 question) applies here, else it is left out with the command's output as the reason


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
    skip_if: str = ""               # a command in the mod's folder: exit 0 means the model is there already (no download)


@dataclass
class Config:
    key: str                        # services.<id>.env.<VAR>, or agent.judge.model, in config.toml
    text: str                       # the question
    choices: str | list[str] = "relay-models"   # the relay's models once it runs, "folder" (an absolute path outside GAIFA), or a list
    required: bool = False          # no answer stops the run; else it's left for later (the report says so)
    restart: str = ""               # a mod id (or "hub") restarted once it's set
    when: str = ""                  # capability-enablement 6.2: "<choose id>=<value>": asked only for that answer
    secret: bool = False            # written to the mod's .env (never config.toml, never a log or a report)


@dataclass
class Find:
    """capability-enablement 7.1: where models of this kind are compared (a leaderboard), shown with the model question."""
    label: str
    url: str
    note: str = ""


@dataclass
class Option:
    value: str
    label: str
    adds: list[str] = field(default_factory=list)   # setups this answer brings in (the relay)


@dataclass
class Choose:
    """capability-enablement 6.2: a choice asked before anything is installed; its answer can add setups."""
    id: str
    text: str
    default: str
    options: list[Option] = field(default_factory=list)

    def option(self, value: str | None) -> Option:
        return next((o for o in self.options if o.value == (value or self.default)), self.options[0])


@dataclass
class Variant:
    accel: str                      # rocm | cuda | xpu | mps | vulkan | cpu
    os: list[str] = field(default_factory=lambda: ["linux"])   # linux (native) | wsl | darwin
    tested: list[str] = field(default_factory=list)            # where it has run for real (os names); else "untested here"
    env: dict[str, str] = field(default_factory=dict)          # for its steps, check and smoke, and the mod ([services.<id>.env])
    steps: list[Step] | None = None                            # its own steps; None: the block's
    check: str = ""                                            # its own check; "": the block's
    smoke: str = ""                                            # its own smoke; "": the block's
    note: str = ""                                             # one line for the plan ("slow on the CPU")
    needs: list[str] | None = None                             # its own host commands; None: the block's


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
    choose: list[Choose] = field(default_factory=list)   # capability-enablement 6.2: choices before install
    find: list[Find] = field(default_factory=list)       # capability-enablement 7.1: where its models are compared
    variants: list[Variant] = field(default_factory=list)   # version 3; empty: see `effective_variants`
    smoke: str = ""                                          # version 3: real work, run with --smoke
    recommended: bool = False                                # capability-enablement 1.4: offered first, pre-ticked; a chat without it says so

    def effective_variants(self) -> list[Variant]:
        """The declared variants, or the one a version-2 block stands for."""
        if self.variants:
            return self.variants
        if self.gpu:
            return [Variant("rocm", ["linux"], ["linux"])]
        return [Variant("cpu", list(OSES), ["linux"])]

    def runs_on(self) -> list[str]:
        """Its accels, in ACCELS order."""
        have = {v.accel for v in self.effective_variants()}
        return [a for a in ACCELS if a in have]


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
    if not isinstance(d.get("next", ""), str):
        return None, f"{where}: `next` must be a string"
    if d.get("optional") and not d.get("ask"):
        return None, f"{where}: an `optional` step needs an `ask` (its question)"
    if not isinstance(d.get("ask_if", ""), str):
        return None, f"{where}: `ask_if` must be a command"
    return Step(run=d["run"].strip(), what=d["what"].strip(), ask=d.get("ask", "").strip(), interactive=d.get("interactive", False),
                skip_if=d.get("skip_if", "").strip(), optional=d.get("optional", False), next=d.get("next", "").strip(),
                ask_if=d.get("ask_if", "").strip()), None


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
    for key in ("revision", "licence", "next", "skip_if"):
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
                   next=d.get("next", "").strip(), start_op=so.strip() if so else "", start_body=dict(d.get("start_body", {})),
                   skip_if=d.get("skip_if", "").strip()), None


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
    if not (choices in ("relay-models", "folder", "text", "endpoint-models") or _strs(choices)):
        return None, f"{where}: `choices` must be \"relay-models\", \"folder\", \"text\", \"endpoint-models\" or a list of strings"
    if not isinstance(d.get("required", False), bool) or not isinstance(d.get("restart", ""), str):
        return None, f"{where}: `required` is true or false, `restart` a mod id or \"hub\""
    when = d.get("when", "")
    if not isinstance(when, str) or (when and "=" not in when):
        return None, f"{where}: `when` must be \"<choose id>=<value>\""
    if not isinstance(d.get("secret", False), bool) or (d.get("secret") and not d["key"].startswith("services.")):
        return None, f"{where}: `secret` is true or false, and only for a services.<id>.env key (it goes to the mod's .env)"
    return Config(key=d["key"], text=d["text"].strip(), choices=choices, required=d.get("required", False), restart=d.get("restart", "").strip(),
                  when=when.strip(), secret=d.get("secret", False)), None


def _find(i: int, d: Any) -> tuple[Find | None, str | None]:
    where = f"find[{i}]"
    if not isinstance(d, dict) or set(d) - FIND:
        return None, f"{where}: a table with label, url and an optional note ([[find]])"
    label, url, note = d.get("label"), d.get("url"), d.get("note", "")
    if not isinstance(label, str) or not label.strip() or len(label) > 80:
        return None, f"{where}: `label` must be a short string (at most 80 characters)"
    if not isinstance(url, str) or not url.startswith("https://") or " " in url:
        return None, f"{where}: `url` must be an https:// link"
    if not isinstance(note, str):
        return None, f"{where}: `note` must be a string"
    return Find(label.strip(), url.strip(), note.strip()), None


def _choose(i: int, d: Any) -> tuple[Choose | None, str | None]:
    where = f"choose[{i}]"
    if not isinstance(d, dict):
        return None, f"{where} must be a table ([[choose]])"
    unknown = sorted(set(d) - CHOOSE)
    if unknown:
        return None, f"{where}: unknown key(s) {', '.join(unknown)} (allowed: {', '.join(sorted(CHOOSE))})"
    for key in ("id", "text", "default"):
        if not isinstance(d.get(key), str) or not d[key].strip():
            return None, f"{where}: `{key}` must be a non-empty string"
    opts = d.get("options")
    if not isinstance(opts, list) or len(opts) < 2:
        return None, f"{where}: `options` must be at least two tables ([[choose.options]])"
    out = []
    for j, o in enumerate(opts):
        if not isinstance(o, dict) or set(o) - OPTION or not isinstance(o.get("value"), str) or not isinstance(o.get("label"), str):
            return None, f"{where}.options[{j}]: value and label strings, and optional adds (setup ids)"
        if "adds" in o and not (_strs(o["adds"]) or o["adds"] == []):
            return None, f"{where}.options[{j}]: `adds` must be a list of setup ids"
        out.append(Option(o["value"].strip(), o["label"].strip(), [a.strip() for a in o.get("adds", [])]))
    if d["default"] not in {o.value for o in out}:
        return None, f"{where}: `default` must be one of its options' values"
    return Choose(d["id"].strip(), d["text"].strip(), d["default"].strip(), out), None


def _variant(i: int, d: Any) -> tuple[Variant | None, str | None]:
    where = f"variants[{i}]"
    if not isinstance(d, dict):
        return None, f"{where} must be a table ([[variants]])"
    unknown = sorted(set(d) - VARIANT)
    if unknown:
        return None, f"{where}: unknown key(s) {', '.join(unknown)} (allowed: {', '.join(sorted(VARIANT))})"
    if d.get("accel") not in ACCELS:
        return None, f"{where}: `accel` must be one of {', '.join(ACCELS)}"
    oses = d.get("os", ["linux"])
    if not _strs(oses) or not oses or any(o not in OSES for o in oses):
        return None, f"{where}: `os` must be a list of {', '.join(OSES)}"
    tested = d.get("tested", False)
    if isinstance(tested, bool):
        tested = list(oses) if tested else []
    elif not (_strs(tested) and all(o in OSES for o in tested)):
        return None, f"{where}: `tested` must be true, false or a list of {', '.join(OSES)}"
    env = d.get("env", {})
    if not isinstance(env, dict) or not all(isinstance(k, str) and k and isinstance(v, str) for k, v in env.items()):
        return None, f"{where}: `env` must be a table of NAME = \"value\" strings"
    steps: list[Step] | None = None
    if "steps" in d:
        if not isinstance(d["steps"], list):
            return None, f"{where}: `steps` must be an array of tables"
        steps = []
        for j, s in enumerate(d["steps"]):
            step, problem = _step(j, s)
            if problem:
                return None, f"{where}.{problem}"
            steps.append(step)
    for key in ("check", "smoke", "note"):
        if not isinstance(d.get(key, ""), str):
            return None, f"{where}: `{key}` must be a string"
    if "needs" in d and not (_strs(d["needs"]) or d["needs"] == []):
        return None, f"{where}: `needs` must be a list of commands"
    return Variant(d["accel"], list(oses), list(tested), dict(env), steps, d.get("check", "").strip(), d.get("smoke", "").strip(),
                   d.get("note", "").strip(), [s.strip() for s in d["needs"]] if "needs" in d else None), None


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
    if "recommended" in data:
        if not isinstance(data["recommended"], bool):
            return None, "`recommended` must be true or false"
        out.recommended = data["recommended"]
    if "smoke" in data:
        if not isinstance(data["smoke"], str) or not data["smoke"].strip():
            return None, "`smoke` must be a non-empty command"
        out.smoke = data["smoke"].strip()
    for key, fn, into in (("steps", _step, out.steps), ("suggest", _suggest, out.suggest), ("config", _config, out.config),
                          ("variants", _variant, out.variants), ("choose", _choose, out.choose), ("find", _find, out.find)):
        v = data.get(key, [])
        if not isinstance(v, list):
            return None, f"`{key}` must be an array of tables ([[{key}]])"
        for i, d in enumerate(v):
            item, problem = fn(i, d)
            if problem:
                return None, problem
            into.append(item)
    if out.variants and out.gpu is None:
        out.gpu = any(v.accel != "cpu" for v in out.variants)
    return out, None
