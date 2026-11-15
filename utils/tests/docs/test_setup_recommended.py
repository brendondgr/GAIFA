"""capability-enablement 1.4: `recommended = true` in a setup block, read per mod for its summary; the recommended set."""

from __future__ import annotations

from pathlib import Path

from utils.setupdocs.block import read
from utils.setupdocs.envs import recommended
from utils.tests.conftest import REPO

RECOMMENDED = {"workspace", "web", "searxng", "decide", "embed", "mcp", "calendar"}   # and relay, with its pin


def test_the_key_parses():
    s, problem = read({"summary": "x", "recommended": True})
    assert problem is None and s.recommended is True
    s, problem = read({"summary": "x"})
    assert s.recommended is False
    _, problem = read({"summary": "x", "recommended": "yes"})
    assert problem == "`recommended` must be true or false"


def test_the_recommended_set():
    mods = {d.name for d in (REPO / "services").iterdir() if (d / "service.toml").is_file() and not d.name.startswith("_")}
    assert {m for m in mods if recommended(REPO / "services" / m)} == RECOMMENDED & mods
    assert not recommended(REPO / "services" / "agent")     # the agent is required, not recommended


def test_only_the_mods_own_block_counts(tmp_path: Path):
    d = tmp_path / "web" / "setup"
    d.mkdir(parents=True)
    (d / "other.md").write_text('<!-- gaifa-setup\nid = "web-extra"\ntitle = "x"\nsummary = "x"\nrecommended = true\n-->\n')
    assert not recommended(tmp_path / "web")
    (d / "web.md").write_text('<!-- gaifa-setup\nid = "web"\ntitle = "x"\nsummary = "x"\nrecommended = true\n-->\n')
    assert recommended(tmp_path / "web")
