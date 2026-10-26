"""`ignore_gap` (plan mod-repos 1.1): what GAIFA ignores in a mod that the mod's own rules don't."""

from __future__ import annotations

import subprocess
from pathlib import Path

from utils.repos import ignore_gap


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


def _project(tmp_path: Path, root_rules: str, mod_rules: str | None) -> Path:
    root = tmp_path / "gaifa"
    mod = root / "services" / "m"
    (mod / ".venv" / "bin").mkdir(parents=True)
    (mod / ".venv" / "bin" / "python").write_text("")
    (mod / "runtime").mkdir()
    (mod / "runtime" / "engine.bin").write_text("x")
    (mod / ".env").write_text("KEY=secret\n")
    (mod / "data").mkdir()
    (mod / "data" / "keep.json").write_text("{}")
    (mod / "app.py").write_text("")
    (root / ".gitignore").write_text(root_rules)
    if mod_rules is not None:
        (mod / ".gitignore").write_text(mod_rules)
    _git(root, "init", "-q")
    _git(root, "add", "-A")
    _git(root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init")
    return root


ROOT_RULES = "/services/*/.venv/\n/services/*/runtime/\n/services/*/.env\n"


def test_covered_mod_has_no_gap(tmp_path):
    root = _project(tmp_path, ROOT_RULES, ".venv/\nruntime/\n.env\n")
    assert ignore_gap(root, "m") == []


def test_rules_only_the_root_has(tmp_path):
    root = _project(tmp_path, ROOT_RULES, ".venv/\n")
    assert sorted(ignore_gap(root, "m")) == [".env", "runtime/"]


def test_no_own_gitignore(tmp_path):
    root = _project(tmp_path, ROOT_RULES, None)
    assert sorted(ignore_gap(root, "m")) == [".env", ".venv/", "runtime/"]


def test_folder_contents_rule_covers_the_folder(tmp_path):
    root = _project(tmp_path, ROOT_RULES, ".venv/\n.env\nruntime/*\n")
    assert ignore_gap(root, "m") == []


def test_negation_that_wins_in_gaifa_too(tmp_path):
    # The mod's own `!.env` overrides the root's rule in GAIFA as well: nothing is ignored, no gap.
    root = _project(tmp_path, ROOT_RULES, ".venv/\nruntime/\n*.env\n!.env\n")
    assert ignore_gap(root, "m") == []


def test_nested_gitignore(tmp_path):
    root = _project(tmp_path, ROOT_RULES, ".venv/\n.env\n")
    (root / "services" / "m" / "runtime" / ".gitignore").write_text("*\n")   # inside runtime: skipped
    assert ignore_gap(root, "m") == ["runtime/"]


def test_nothing_ignored(tmp_path):
    root = _project(tmp_path, "", None)
    assert ignore_gap(root, "m") == []
