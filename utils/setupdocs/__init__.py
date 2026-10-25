"""Setup docs (plan 23): the mods index in `docs/setup/README.md` and the support matrix in
`docs/platforms.md` (plan 40.4), both committed, and a local inventory of this machine's models in
`data/state/setup/models/` (gitignored: which models to set up is each person's choice, plan 23.6). Standard library only, so `gaifa docs` runs without the hub. A model
doc's generated part sits between markers; everything outside them is hand-written and kept byte
for byte. Setup docs (`services/<id>/setup/*.md`) are read, never written.
"""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import envs as envs_mod
from . import render
from .envs import Env, load_envs, match, references, under

__all__ = ["Report", "sync", "Env", "load_envs"]

INVENTORY = Path("data") / "state" / "setup" / "models"   # local, gitignored
BLOCK = re.compile(re.escape(render.START) + r".*?" + re.escape(render.END), re.S)


@dataclass
class Report:
    written: list[str] = field(default_factory=list)     # docs created or changed (or that would be, in check mode)
    removed: list[str] = field(default_factory=list)     # inventory docs of removed models, no hand text: deleted
    stale: list[str] = field(default_factory=list)       # check mode: a committed generated part is out of date
    missing: list[str] = field(default_factory=list)     # check mode: a committed generated file is missing
    orphans: list[str] = field(default_factory=list)     # inventory docs of removed models, kept for their hand text
    env_problems: dict[str, str] = field(default_factory=dict)
    uncovered: list[str] = field(default_factory=list)   # inventory note: models no setup doc's `models` glob matches
    unsourced: list[str] = field(default_factory=list)   # inventory note: models with no recorded source
    uncovered_mods: list[str] = field(default_factory=list)  # mods without a setup doc

    def problems(self, strict: bool = False) -> list[str]:
        """What fails `gaifa docs --check`: only what's committed (the mods index, the setup docs).
        The inventory is local, so its gaps are notes, never failures."""
        out = [f"stale: {p}" for p in self.stale] + [f"missing: {p}" for p in self.missing]
        out += [f"setup doc {p}: {m}" for p, m in self.env_problems.items()]
        if strict:
            out += [f"mod {m} has no setup doc (services/{m}/setup/)" for m in self.uncovered_mods]
        return out


def _models_dir(root: Path) -> Path:
    try:
        cfg = tomllib.loads((root / "config.toml").read_text())
    except (OSError, tomllib.TOMLDecodeError):
        cfg = {}
    return root / (cfg.get("paths", {}).get("models") or "data/models")


def _registry(models_dir: Path) -> dict[str, dict[str, Any]]:
    try:
        data = json.loads((models_dir / "registry.json").read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return {k: v for k, v in (data.get("models") or {}).items() if isinstance(v, dict) and isinstance(v.get("path"), str)}


def _mod_dirs(root: Path) -> dict[str, list[str]]:
    """Each mod's `[models] dirs` from its service.toml (the registry's "used by", architecture §8)."""
    out: dict[str, list[str]] = {}
    for d in envs_mod.mod_dirs(root):
        try:
            m = tomllib.loads((d / "service.toml").read_text())
        except (OSError, tomllib.TOMLDecodeError):
            continue
        dirs = (m.get("models") or {}).get("dirs") or []
        out[d.name] = [s.strip("/") for s in dirs if isinstance(s, str) and s.strip("/")]
    return out


def used_by(e: dict[str, Any], mods: dict[str, list[str]]) -> list[str]:
    out = [s for s in e.get("services") or [] if isinstance(s, str)]
    for mid, dirs in mods.items():
        if mid not in out and any(under(e["path"], d) for d in dirs):
            out.append(mid)
    return out


def names(e: dict[str, Any]) -> list[str]:
    """What a workflow or profile would mention: the weight files' names and the Hugging Face repo."""
    out = []
    for f in e.get("files", []):
        if (f.get("role") or "weights") in ("weights", "model") or len(e["files"]) == 1:
            out.append(f["path"].rsplit("/", 1)[-1])
    if not e["path"].startswith("hf-cache/") and "." in e["path"].rsplit("/", 1)[-1]:
        out.append(e["path"].rsplit("/", 1)[-1])
    repo = (e.get("source") or {}).get("repo")
    if repo:
        out.append(repo)
    return sorted(set(out))


def _hand(text: str) -> str:
    """What's outside the generated block."""
    return BLOCK.sub("", text)


def _hand_empty(text: str) -> bool:
    rest = re.sub(r"(?m)^##\s+(Where to get it|What to look for|Notes)\s*$", "", _hand(text))
    return not rest.strip()


def where_to_get(text: str) -> str:
    m = re.search(r"(?ms)^##\s+Where to get it\s*$(.*?)(?=^##\s|\Z)", _hand(text))
    return m.group(1).strip() if m else ""


def _put(path: Path, text: str, check: bool, report: Report, rel: str) -> None:
    old = path.read_text() if path.exists() else None
    if old == text:
        return
    if check:
        (report.stale if old is not None else report.missing).append(rel)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".md.tmp")
    tmp.write_text(text)
    tmp.replace(path)
    report.written.append(rel)


def sync(root: Path, ids: list[str] | None = None, check: bool = False) -> Report:
    """Regenerate the mods index and the local model inventory (all models, or `ids`). In check mode
    nothing is written and only the committed index is compared: a change is reported as stale."""
    root = Path(root)
    report = Report()
    envs, report.env_problems = load_envs(root)
    models_dir_data = _models_dir(root)
    reg = _registry(models_dir_data)
    mods = _mod_dirs(root)
    out_dir = root / INVENTORY
    rows: list[tuple[str, dict[str, Any], list[Env]]] = []
    for mid, e in sorted(reg.items()):
        matched = match(e["path"], envs)
        rows.append((mid, e, matched))
        users = used_by(e, mods)
        if not matched:
            report.uncovered.append(mid)
        doc = out_dir / f"{mid}.md"
        old = doc.read_text() if doc.exists() else None
        if not render.has_source(e) and not where_to_get(old or ""):
            report.unsourced.append(mid)
        if check or (ids is not None and mid not in ids):
            continue
        block = render.model_block(mid, e, users, matched, references(names(e), envs, root), doc, root)
        if old is None:
            new = block + "\n\n" + (render.HAND_WITH_SOURCE if render.has_source(e) else render.HAND_NO_SOURCE)
        elif BLOCK.search(old):
            new = BLOCK.sub(lambda _m: block, old, count=1)
        else:
            new = block + "\n\n" + old
        _put(doc, new, check, report, doc.relative_to(root).as_posix())
    have = {mid for mid, _, _ in rows}
    covered = {v.mod for v in envs}
    report.uncovered_mods = sorted(m for m in mods if m not in covered)
    if out_dir.is_dir() and not check:
        for doc in sorted(out_dir.glob("*.md")):
            mid = doc.stem
            if mid in have:
                continue
            text = doc.read_text()
            rel = doc.relative_to(root).as_posix()
            if mid == "README":
                continue
            if _hand_empty(text):
                doc.unlink()
                report.removed.append(rel)
            else:
                report.orphans.append(rel)
                if BLOCK.search(text):
                    _put(doc, BLOCK.sub(lambda _m: render.orphan_block(mid), text, count=1), check, report, rel)
    if not check and rows:
        index = out_dir / "README.md"
        _put(index, render.inventory_index(rows, index), False, report, index.relative_to(root).as_posix())
    readme = root / "docs" / "setup" / "README.md"
    if readme.exists():
        text = readme.read_text()
        if BLOCK.search(text):
            _put(readme, BLOCK.sub(lambda _m: render.mods_index(envs, readme), text, count=1), check, report, readme.relative_to(root).as_posix())
    page = root / "docs" / "platforms.md"
    if page.exists():
        text = page.read_text()
        if BLOCK.search(text):
            _put(page, BLOCK.sub(lambda _m: render.platforms_matrix(envs, page), text, count=1), check, report, page.relative_to(root).as_posix())
    return report
