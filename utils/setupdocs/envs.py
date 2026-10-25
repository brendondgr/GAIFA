"""Setup docs: `services/<id>/setup/<env>.md` and their `<!-- gaifa-setup … -->` block (docs/mods.md §9;
the version-2 keys are in block.py)."""

from __future__ import annotations

import fnmatch
import re
import subprocess
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .block import TOP as KEYS
from .block import Setup, read

HEAD = re.compile(r"\A\s*<!--\s*gaifa-setup\s*\n(.*?)\n\s*-->", re.S)


@dataclass
class Env:
    id: str
    title: str
    mod: str
    path: Path                      # the doc, absolute
    models: list[str] = field(default_factory=list)
    scan: list[str] = field(default_factory=list)
    setup: Setup = field(default_factory=Setup)   # the version-2 keys: what `gaifa setup` reads


def mod_dirs(root: Path) -> list[Path]:
    """Mod folders: every `services/<id>/` with a service.toml, except `_template` and hidden ones."""
    base = root / "services"
    if not base.is_dir():
        return []
    return sorted(d for d in base.iterdir() if d.is_dir() and not d.name.startswith(("_", ".")) and (d / "service.toml").is_file())


def parse(path: Path, mod: str) -> tuple[Env | None, str | None]:
    """One environment doc → (Env, None) or (None, problem)."""
    try:
        text = path.read_text()
    except OSError as e:
        return None, f"can't read it: {e.strerror or e}"
    m = HEAD.match(text)
    if not m:
        return None, "no <!-- gaifa-setup … --> block at the top"
    try:
        data = tomllib.loads(m.group(1))
    except tomllib.TOMLDecodeError as e:
        return None, f"the gaifa-setup block isn't TOML: {e}"
    unknown = sorted(set(data) - KEYS)
    if unknown:
        return None, f"unknown key(s) {', '.join(unknown)} (allowed: {', '.join(sorted(KEYS))})"
    for key in ("id", "title"):
        if not isinstance(data.get(key), str) or not data[key].strip():
            return None, f"`{key}` must be a non-empty string"
    for key in ("models", "scan"):
        v = data.get(key, [])
        if not isinstance(v, list) or not all(isinstance(s, str) and s.strip() for s in v):
            return None, f"`{key}` must be a list of strings"
    setup, problem = read(data)
    if problem:
        return None, problem
    assert setup is not None
    return Env(id=data["id"], title=data["title"], mod=mod, path=path,
               models=[s.strip().strip("/") for s in data.get("models", [])],
               scan=[s.strip() for s in data.get("scan", [])], setup=setup), None


def load_envs(root: Path) -> tuple[list[Env], dict[str, str]]:
    """Every environment doc in the mods, plus a problem per doc (keyed by its path from the root)."""
    envs: list[Env] = []
    problems: dict[str, str] = {}
    seen: dict[str, str] = {}
    for mod in mod_dirs(root):
        for doc in sorted((mod / "setup").glob("*.md")):
            rel = doc.relative_to(root).as_posix()
            env, problem = parse(doc, mod.name)
            if problem:
                problems[rel] = problem
                continue
            assert env is not None
            if env.id in seen:
                problems[rel] = f"id {env.id!r} is also used by {seen[env.id]}"
                continue
            seen[env.id] = rel
            envs.append(env)
    return envs, problems


def under(path: str, folder: str) -> bool:
    return path == folder or path.startswith(folder + "/")


def matches(model_path: str, pattern: str) -> bool:
    """A `models` glob against a model's path (relative to data/models). A plain folder matches what's under it."""
    if any(c in pattern for c in "*?["):
        return fnmatch.fnmatchcase(model_path, pattern)
    return under(model_path, pattern)


def match(model_path: str, envs: list[Env]) -> list[Env]:
    return [e for e in envs if any(matches(model_path, p) for p in e.models)]


def _token(s: str) -> re.Pattern[str]:
    return re.compile(r"(?<![\w.\-])" + re.escape(s) + r"(?![\w.\-])")   # "loras/x.safetensors" still names x


def tracked(folder: Path) -> set[Path] | None:
    """The files git tracks under `folder`, or None outside a git checkout (then every file counts).
    Only tracked files are scanned, so a model doc reads the same in every clone: gitignored
    third-party workflow packs, for one, exist only on the machine that imported them."""
    try:
        out = subprocess.run(["git", "-C", str(folder), "ls-files", "-z", "--", "."], capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return {(folder / p).resolve() for p in out.stdout.decode(errors="ignore").split("\0") if p}


def references(names: list[str], envs: list[Env], root: Path) -> list[str]:
    """The `scan` files (paths from the root) that mention one of `names` as a whole token:
    a file name or an org/repo, never a substring of a longer name (`ae.safetensors` ≠ `vae.safetensors`)."""
    pats = [_token(n) for n in names if len(n) >= 5]
    if not pats:
        return []
    out: list[str] = []
    for env in envs:
        base = root / "services" / env.mod
        keep = tracked(base) if env.scan else None
        for glob in env.scan:
            for f in sorted(base.glob(glob)):
                if not f.is_file() or (keep is not None and f.resolve() not in keep):
                    continue
                try:
                    text = f.read_text(errors="ignore")
                except OSError:
                    continue
                if any(p.search(text) for p in pats):
                    rel = f.relative_to(root).as_posix()
                    if rel not in out:
                        out.append(rel)
    return out
