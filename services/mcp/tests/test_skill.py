"""mcp-client 5.2: the Blender skill's frontmatter names it and its server, so reading it in a chat loads the Blender
tools (4.1), and the preset points at it. The hub's own test parses every mod's SKILL.md as YAML (skill-sources 1.1)."""

from __future__ import annotations

import re
from pathlib import Path

from presets import presets

SKILL = Path(__file__).resolve().parents[1] / "skills" / "blender" / "SKILL.md"


def frontmatter() -> str:
    text = SKILL.read_text()
    assert text.startswith("---\n")
    return text.split("\n---\n", 1)[0]


def test_the_skill_names_itself_and_its_server():
    fm = frontmatter()
    assert re.search(r"^name: blender$", fm, re.M)
    assert re.search(r"^description: ", fm, re.M)
    assert re.search(r"^metadata:\n  mcp-servers: blender$", fm, re.M)


def test_the_preset_uses_the_skill(tmp_path):
    server = presets(tmp_path)["blender"]["server"]
    assert server["id"] == "blender" and server["skill"] == SKILL.parent.name
