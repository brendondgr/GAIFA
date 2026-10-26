"""Skills and instruction files in a chat's workspace folders (plan skill-sources 2.1; `skills/` is this mod's own skill).

For each folder a call may use (its environment's, and those allowed in its chat), every coding agent's skill
folder (`LOCATIONS`) is looked at one level deep: `<folder>/<location>/<name>/SKILL.md`, in the open skill format
(`skillfmt.py`). Nothing above or outside the folder is read, and a chat with no folders gets nothing.

- **One entry per skill:** the same name with the same text and files in several locations is one skill, with every place
  it was found (`found_in`); the same name with different text in one folder keeps both, each id qualified by its
  agent (`gaifa:claude.plan`).
- **Ids:** `<folder id>:<skill name>`; a skill's file is `<id>/<path>`; an instruction file is `<folder id>:<file>`
  (`gaifa:AGENTS.md`).
- **Instruction files** (`INSTRUCTIONS`, and `.cursor/rules/*.mdc` with `alwaysApply: true`) are listed for the
  agent to read before working in the folder; a `CLAUDE.md` that only imports `@AGENTS.md` is that file, and
  files with the same text are one.
- **The folder's hard limits hold** (`Folders.resolve`): no symlink out, secret files never read, 2 MB, no binary.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

import skillfmt
from folders import Folder, Folders, Refused

LOCATIONS = (
    (".agents/skills", "agents"), (".claude/skills", "claude"), (".codex/skills", "codex"),
    (".gemini/skills", "gemini"), (".cursor/skills", "cursor"), (".github/skills", "copilot"),
    (".opencode/skills", "opencode"), (".cline/skills", "cline"), (".windsurf/skills", "windsurf"),
    (".devin/skills", "devin"), (".goose/skills", "goose"), (".roo/skills", "roo"),
)
INSTRUCTIONS = ("AGENTS.md", "CLAUDE.md", "GEMINI.md", ".github/copilot-instructions.md")
CURSOR_RULES = ".cursor/rules"
PER_FOLDER = 200                 # skills listed per folder
SKILL_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_IMPORT = re.compile(r"^@\S+$")
_cache: dict[tuple[str, int, int], dict[str, Any]] = {}     # SKILL.md by (path, mtime, size): parsed


def _parsed(p: Path) -> dict[str, Any]:
    st = p.stat()
    key = (str(p), st.st_mtime_ns, st.st_size)
    hit = _cache.get(key)
    if hit is None:
        text = p.read_text(errors="replace")
        hit = {**skillfmt.load(text, p.parent.name), "hash": hashlib.sha256(text.encode()).hexdigest()[:16]}
        if len(_cache) > 4000:
            _cache.clear()
        _cache[key] = hit
    return hit


def _found(folders: Folders, f: Folder) -> list[dict[str, Any]]:
    """Every SKILL.md one level under the folder's skill locations, in LOCATIONS order."""
    out = []
    for loc, agent in LOCATIONS:
        try:
            d, _ = folders.resolve(f, loc)
        except Refused:
            continue
        if not d.is_dir():
            continue
        for sub in sorted(d.iterdir()):
            if not SKILL_NAME.match(sub.name):
                continue
            rel = f"{loc}/{sub.name}/SKILL.md"
            try:
                p, _ = folders.resolve(f, rel, read_file=True)
            except Refused:
                continue
            if p.is_file():
                s = _parsed(p)
                files = ",".join(f"{x['path']}:{x['size']}" for x in skillfmt.files(p.parent))
                key = hashlib.sha256(f"{s['hash']}|{files}".encode()).hexdigest()[:16]   # the text and its files
                out.append({"agent": agent, "path": rel, "dir": f"{loc}/{sub.name}", "s": s, "key": key})
    return out


def folder_skills(folders: Folders, f: Folder) -> list[dict[str, Any]]:
    """The folder's skills, one entry per name and text."""
    by: dict[tuple[str, str], dict[str, Any]] = {}
    for x in _found(folders, f):
        s = x["s"]
        name = s["name"] if s["name"] and skillfmt.NAME.match(s["name"]) else x["dir"].rsplit("/", 1)[1].lower()
        k = (name, x["key"])
        if k in by:
            by[k]["found_in"].append(x["path"])
            continue
        by[k] = {"name": name, "description": s["description"], "agent": x["agent"], "path": x["path"], "dir": x["dir"],
                 "hash": x["key"], "found_in": [x["path"]], "problems": s["problems"], "meta": s["meta"],
                 "model_invocable": not skillfmt.flag(s["meta"], "disable-model-invocation")}
        if len(by) >= PER_FOLDER:
            break
    rows = list(by.values())
    clash = {r["name"] for r in rows if sum(1 for o in rows if o["name"] == r["name"]) > 1}
    for r in rows:
        r["id"] = f"{f.id}:{r['agent']}.{r['name']}" if r["name"] in clash else f"{f.id}:{r['name']}"
    return rows


def folder_instructions(folders: Folders, f: Folder) -> list[dict[str, Any]]:
    """The folder's instruction files: one per text, a CLAUDE.md that only imports another file folded into it."""
    found = []
    rules = []
    try:
        rd, _ = folders.resolve(f, CURSOR_RULES)
        if rd.is_dir():
            rules = [f"{CURSOR_RULES}/{p.name}" for p in sorted(rd.glob("*.mdc"))]
    except Refused:
        pass
    for rel in (*INSTRUCTIONS, *rules):
        try:
            p, _ = folders.resolve(f, rel, read_file=True)
        except Refused:
            continue
        if not p.is_file():
            continue
        text = p.read_text(errors="replace")
        if rel.endswith(".mdc") and not skillfmt.flag(skillfmt.parse(text)["meta"], "alwaysApply"):
            continue
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        imports = [ln[1:] for ln in lines if _IMPORT.match(ln)]
        found.append({"file": rel, "text": text, "lines": len(text.splitlines()), "only_imports": bool(lines) and len(imports) == len(lines),
                      "imports": imports, "hash": hashlib.sha256(text.encode()).hexdigest()[:16]})
    out: list[dict[str, Any]] = []
    for x in found:
        if x["only_imports"]:
            target = next((o for o in out if o["file"] in x["imports"]), None) or \
                next((o for o in found if o["file"] in x["imports"] and not o["only_imports"]), None)
            if target is not None:
                target.setdefault("also", []).append(x["file"])
                continue
        same = next((o for o in out if o["hash"] == x["hash"]), None)
        if same is not None:
            same.setdefault("also", []).append(x["file"])
            continue
        out.append(x)
    return [{"id": f"{f.id}:{x['file']}", "file": x["file"], "lines": x["lines"], "also": x.get("also", [])} for x in out]


def listing(folders: Folders) -> dict[str, Any]:
    """`GET /v1/skills`: the skills and instruction files of every folder in this view."""
    skills, instructions = [], []
    for f in folders.list():
        pub = f.public(folders.caps)
        if not pub["exists"]:
            continue
        where = {"id": f.id, "name": pub["name"], "path": f.path}
        skills += [{**r, "folder": where} for r in folder_skills(folders, f)]
        instructions += [{**r, "folder": where} for r in folder_instructions(folders, f)]
    return {"skills": skills, "instructions": instructions}


def read(folders: Folders, ref: str, named: list[str] | None = None) -> dict[str, Any]:
    """`POST /v1/skills/read`: a skill's body and its files, one of its files (`<id>/<path>`), or an instruction file."""
    fid, sep, rest = (ref or "").strip().partition(":")
    if not sep or not rest:
        raise Refused("not_found", f"{ref!r} isn't a workspace skill id (<folder>:<skill>)", "", 404)
    f = folders.get(fid)
    instr = {i["file"]: i for i in folder_instructions(folders, f)}
    if rest in instr or any(rest in i["also"] for i in instr.values()):
        p, _ = folders.resolve(f, rest, read_file=True, named=named)
        return {"id": ref, "kind": "instructions", "text": p.read_text(errors="replace")}
    sid, _, path = rest.partition("/")
    rows = {r["id"].split(":", 1)[1]: r for r in folder_skills(folders, f)}
    r = rows.get(sid)
    if r is None:
        raise Refused("not_found", f"no skill {sid!r} in the folder {f.id}", "the chat's skills are listed in its instructions", 404)
    if not path:
        p, _ = folders.resolve(f, r["path"], read_file=True)
        sdir, _ = folders.resolve(f, r["dir"])
        listed = [x for x in skillfmt.files(sdir) if _readable(folders, f, f"{r['dir']}/{x['path']}")]
        return {"id": ref, "kind": "skill", "text": skillfmt.parse(p.read_text(errors="replace"))["body"], "files": listed,
                "name": r["name"], "description": r["description"]}
    p, _ = folders.resolve(f, f"{r['dir']}/{path}", read_file=True, named=named)
    sdir, _ = folders.resolve(f, r["dir"])
    try:
        return {"id": ref, "kind": "file", "text": skillfmt.read_file(sdir, path)}
    except skillfmt.SkillFileError as e:
        raise Refused(e.code, e.detail, "", 404 if e.code == "not_found" else 422) from None


def _readable(folders: Folders, f: Folder, rel: str) -> bool:
    try:
        folders.resolve(f, rel)
        return True
    except Refused:
        return False
