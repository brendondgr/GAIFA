"""Phase 27: the workspace mod's manifest, and the `[tools]` fields it brought (`cap_kb`)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from utils.manifest import ToolSpec, parse

ROOT = Path(__file__).resolve().parents[3]


def test_cap_kb_validates():
    assert ToolSpec.model_validate({"op": "POST /v1/x", "cap_kb": 64}).cap_kb == 64
    assert ToolSpec.model_validate({"op": "POST /v1/x"}).cap_kb is None
    for bad in (0, 257):
        with pytest.raises(ValidationError):
            ToolSpec.model_validate({"op": "POST /v1/x", "cap_kb": bad})


def test_workspace_reading_tools():
    mod = parse(ROOT / "services" / "workspace")
    assert mod.errors == [] and mod.manifest
    m = mod.manifest
    assert m.run.port == 5103 and m.agent.skills == "skills"
    for name in ("tree", "read", "search", "git"):
        t = m.tools[name]
        assert t.risk == "read" and t.grant_key == "arg:folder" and t.cap_kb, name
    assert m.tools["folders"].op == "GET /v1/folders" and m.tools["folders"].core
    assert (ROOT / "services" / "workspace" / "skills" / "workspace" / "SKILL.md").is_file()


def test_workspace_editing_tools():
    m = parse(ROOT / "services" / "workspace").manifest
    assert m is not None
    for name, risk in (("edit", "write"), ("write", "write"), ("move", "write"), ("delete", "destructive"), ("git_commit", "write")):
        assert (m.tools[name].risk, m.tools[name].grant_key) == (risk, "arg:folder"), name
