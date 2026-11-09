"""calendar 4.2: the calendar mod's tools: the manifest loads, its preflight is declared, each tool's op is a route
of the mod's own API (its OpenAPI, from the mod's venv), and the risks the plan gives."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from utils.manifest import discover

ROOT = Path(__file__).resolve().parents[3]
MOD = ROOT / "services" / "calendar"


def test_manifest_tools_and_preflight():
    m = next(x for x in discover([ROOT / "services"]) if x.id == "calendar")
    assert m.ok, m.errors
    t = m.manifest.tools
    assert set(t) == {"agenda", "search", "when", "free", "add", "update", "done", "delete", "propose", "plan_day"}
    assert m.manifest.agent.limits == "POST /v1/limits"
    assert {k for k, v in t.items() if v.core} == {"agenda", "when", "add"}
    assert all(t[k].risk == "write" for k in ("add", "update", "done", "delete"))
    assert all(t[k].risk == "read" for k in ("propose", "plan_day"))


def test_each_op_is_a_route():
    py = MOD / ".venv" / "bin" / "python"
    if not py.exists():
        pytest.skip("the calendar mod isn't installed (gaifa install calendar)")
    r = subprocess.run([str(py), "-c", "import json, server; print(json.dumps(server.create_app(':memory:', '/tmp', background=False).openapi()['paths']))"],
                       cwd=MOD, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    paths = json.loads(r.stdout)
    m = next(x for x in discover([ROOT / "services"]) if x.id == "calendar")
    for name, spec in m.manifest.tools.items():
        method, path = spec.op.split(" ", 1)
        assert method.lower() in paths.get(path, {}), (name, spec.op)
