"""26.2: the `network` and `execute` risks and `grant_key` (plan 25.1–25.2) are accepted in `[tools]`,
and the web mod declares its two tools with them."""

from __future__ import annotations

from pathlib import Path

from utils.manifest import ToolSpec, parse
from utils.tools.api import ToolIndexItem

ROOT = Path(__file__).resolve().parents[3]


def test_new_risks_and_grant_key_validate():
    for risk in ("network", "execute"):
        spec = ToolSpec.model_validate({"op": "POST /v1/x", "risk": risk, "grant_key": "url:host"})
        assert spec.risk == risk and spec.grant_key == "url:host"
    assert ToolSpec.model_validate({"op": "GET /v1/x"}).grant_key is None
    assert ToolIndexItem(name="web_fetch", mod="web", risk="network", core=False, summary="", available=True).risk == "network"


def test_web_mod_declares_network_tools():
    mod = parse(ROOT / "services" / "web")
    assert mod.errors == [] and mod.manifest
    tools = mod.manifest.tools
    assert (tools["search"].op, tools["search"].risk, tools["search"].grant_key) == ("POST /v1/search", "network", "const:search")
    assert (tools["fetch"].op, tools["fetch"].risk, tools["fetch"].grant_key) == ("POST /v1/fetch", "network", "url:host")
    assert tools["search"].core and tools["fetch"].core      # always loaded: answers are grounded without load_tools first
    assert mod.manifest.run.port == 5102
    assert (ROOT / "services" / "web" / "skills" / "researching" / "SKILL.md").is_file()
