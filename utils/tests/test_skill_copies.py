"""skill-sources 1.3: `.agents/skills/` (Codex and other agents) is an exact copy of `.claude/skills/`."""

import filecmp
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _files(d: Path) -> set[str]:
    return {p.relative_to(d).as_posix() for p in d.rglob("*") if p.is_file() and "__pycache__" not in p.parts}


def test_the_two_skill_trees_are_identical():
    a, b = ROOT / ".claude" / "skills", ROOT / ".agents" / "skills"
    assert _files(a) == _files(b), "copy .claude/skills/ to .agents/skills/ (cp -a .claude/skills/. .agents/skills/)"
    differ = [f for f in sorted(_files(a)) if not filecmp.cmp(a / f, b / f, shallow=False)]
    assert not differ, f"these differ: {differ}; edit .claude/skills/ and copy it to .agents/skills/"
