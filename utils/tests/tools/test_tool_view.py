"""46.1: a tool's default view: validation, carried in the catalog (manifest, hub tools), and the installed mods' views."""

from __future__ import annotations

import tomllib

import pytest

from utils.tests.conftest import REPO, needs_mods
from utils.tools import views


def test_a_table_view_is_cleaned():
    v, p = views.check({"kind": "table", "rows": "jobs", "columns": ["id", {"key": "request.engine", "label": "Engine"},
                                                                     {"key": "created", "format": "time"}]})
    assert p == [] and v == {"kind": "table", "rows": "jobs", "columns": [{"key": "id", "label": "id"},
                                                                         {"key": "request.engine", "label": "Engine"},
                                                                         {"key": "created", "label": "created", "format": "time"}]}
    assert views.check(None) == (None, [])


@pytest.mark.parametrize("bad, word", [
    ({"kind": "pie"}, "kind"), ({"kind": "table", "rows": "a b"}, "rows"), ({"kind": "table", "columns": [{"label": "x"}]}, "key"),
    ({"kind": "table", "columns": [{"key": "x", "format": "money"}]}, "format"), ({"kind": "bar", "rows": "m"}, "x"), ("table", "view must"),
])
def test_bad_views_say_why(bad, word):
    v, p = views.check(bad)
    assert v is None and any(word in x for x in p), p


def test_a_chart_view():
    v, p = views.check({"kind": "hbar", "rows": "models", "x": "name", "y": ["size_bytes"], "unit": "bytes"})
    assert p == [] and v["y"] == ["size_bytes"] and v["unit"] == "bytes"


@pytest.mark.parametrize("mod, tool", [pytest.param("gen3d", "list_jobs", marks=needs_mods("gen3d")), ("stt", "list_models"),
                                       pytest.param("lcpp", "list_llms", marks=needs_mods("lcpp")), ("searxng", "engines"), ("vllm", "list_profiles")])
def test_the_installed_mods_views_are_valid(mod, tool):
    spec = tomllib.loads((REPO / "services" / mod / "service.toml").read_text())["tools"][tool]
    v, p = views.check(spec["view"])
    assert p == [] and v["kind"] == "table"


async def test_the_catalog_carries_hub_views(th):
    r = (await th.client.get("/api/tools", params={"names": "hub_list_models,hub_list_sessions"})).json()
    assert {t["name"]: t["view"]["rows"] for t in r} == {"hub_list_models": "models", "hub_list_sessions": "sessions"}


async def test_the_model_is_told_the_result_is_shown(th):
    model = (await th.client.get("/api/tools", params={"names": "hub_list_models", "view": "model"})).json()[0]
    full = (await th.client.get("/api/tools", params={"names": "hub_list_models"})).json()[0]
    assert "sees its result as a table" in model["description"] and "sees its result" not in full["description"]
