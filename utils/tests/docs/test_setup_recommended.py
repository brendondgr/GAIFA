"""capability-enablement 1.4: `recommended = true` in a setup block, read per mod for its summary; the recommended set."""

from __future__ import annotations

from pathlib import Path

from utils.setupdocs.block import read
from utils.setupdocs.envs import recommended
from utils.tests.conftest import REPO

RECOMMENDED = {"relay", "workspace", "web", "searxng", "decide", "embed", "mcp", "calendar"}   # relay since its pin of 2026-11-16


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


def test_find_parses_and_reaches_the_plan():
    """capability-enablement 7.1: [[find]] (label, an https URL, a note) where models of a kind are compared."""
    s, problem = read({"summary": "x", "find": [{"label": "Compared", "url": "https://example.org/board", "note": "local only"}]})
    assert problem is None and s.find[0].url == "https://example.org/board"
    assert read({"summary": "x", "find": [{"label": "x", "url": "http://insecure.example"}]})[1].endswith("an https:// link")
    assert read({"summary": "x", "find": [{"label": "x" * 81, "url": "https://e.org"}]})[1].startswith("find[0]: `label`")
    from utils.setupdocs.envs import parse
    env, _ = parse(REPO / "services" / "embed" / "setup" / "embed.md", "embed")
    assert env.setup.find[0].url == "https://huggingface.co/spaces/mteb/leaderboard"
    env, _ = parse(REPO / "services" / "decide" / "setup" / "decide.md", "decide")
    assert env.setup.find[0].url == "https://huggingface.co/spaces/multimodalart/jev-decision-index"
