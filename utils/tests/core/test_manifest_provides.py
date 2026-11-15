"""capability-enablement 1.4: `[agent] provides`, what a mod lets the agent do ("I can't …"), parsed, checked and in
every mod's summary; every mod in this checkout says it."""

from __future__ import annotations

import tomllib
from pathlib import Path

from utils import manifest as mf
from utils.tests.conftest import REPO

BASE = '''id = "{id}"
name = "Thing"
[run]
command = ["python3", "x.py"]
port = 5150
health = "/health"
'''


def mod(tmp_path: Path, extra: str, sid: str = "thing") -> mf.Mod:
    d = tmp_path / "services" / sid
    d.mkdir(parents=True)
    (d / "service.toml").write_text(BASE.format(id=sid) + extra)
    return next(m for m in mf.discover([tmp_path / "services"]) if m.id == sid)


def test_parsed_and_tidied(tmp_path):
    m = mod(tmp_path, '[agent]\nprovides = "search the web   and read pages"\n')
    assert not m.errors and m.manifest.agent.provides == "search the web and read pages"


def test_optional(tmp_path):
    m = mod(tmp_path, "")
    assert not m.errors and m.manifest.agent.provides is None


def test_too_long_is_a_manifest_error(tmp_path):
    m = mod(tmp_path, f'[agent]\nprovides = "{"x" * 81}"\n')
    assert m.errors and "80" in m.errors[0]


def test_empty_is_a_manifest_error(tmp_path):
    m = mod(tmp_path, '[agent]\nprovides = "  "\n')
    assert m.errors


def test_every_mod_here_says_what_it_gives():
    submodules = {"relay", "lcpp", "tts", "gen3d"}    # their own repositories: their lines land with their pins
    missing = []
    for toml in sorted((REPO / "services").glob("*/service.toml")):
        sid = toml.parent.name
        if sid.startswith("_") or sid in submodules:
            continue
        data = tomllib.loads(toml.read_text())
        p = (data.get("agent") or {}).get("provides")
        if not p or len(p) > 80:
            missing.append(sid)
    assert missing == []


def test_the_template_shows_it():
    assert 'provides = "' in (REPO / "services" / "_template" / "service.toml").read_text()
