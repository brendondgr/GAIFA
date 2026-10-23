"""48.1: what can be @-mentioned: the mods' declared kinds, validated, listed through GET /api/mentions."""

from __future__ import annotations

import httpx
import pytest
from pydantic import ValidationError

from utils.manifest import MentionSpec
from utils.routes.mentions import items_of
from utils.tests.services.conftest import ready


def test_a_spec_is_checked():
    assert MentionSpec(kind="voice", list="GET /v1/voices", fills=["speak.name"]).value == "name"
    for bad in ({"kind": "Voice!", "list": "GET /v1/x"}, {"kind": "voice", "list": "GET /v1/x", "fills": ["name"]}):
        with pytest.raises(ValidationError):
            MentionSpec(**bad)


def test_items_from_objects_and_strings():
    objs = MentionSpec(kind="voice", list="GET /v1/voices", rows="custom", fills=["speak.name"])
    strs = MentionSpec(kind="voice", list="GET /v1/voices", rows="kokoro", value="", fills=["speak.name"])
    body = {"custom": [{"name": "Brendon"}, {"nope": 1}], "kokoro": ["af_heart", ""]}
    assert items_of(body, objs, "tts", "Speech") == [{"kind": "voice", "id": "Brendon", "label": "Brendon", "sub": "Speech", "fills": ["tts_speak.name"]}]
    assert [m["id"] for m in items_of(body, strs, "tts", "Speech")] == ["af_heart"]
    lab = MentionSpec(kind="engine", list="GET /v1/options", rows="engines", value="id", label="label")
    assert items_of({"engines": [{"id": "cube3d", "label": "Cube3D"}]}, lab, "gen3d", "3D")[0]["label"] == "Cube3D"


async def test_the_route_lists_and_searches(rig, serve):
    d = rig.add("fake-ok")
    with open(d / "service.toml", "a") as f:
        f.write('\n[[agent.mentions]]\nkind = "stat"\nlist = "GET /v1/status"\nrows = "stats"\nvalue = "label"\nfills = ["hello.name"]\n')
    served = await serve()
    await ready(served, "fake-ok")
    async with httpx.AsyncClient(base_url=served.url) as c:
        all_ = (await c.get("/api/mentions")).json()
        assert {m["id"] for m in all_} == {"Requests", "Outputs today"} and all_[0]["fills"] == ["fake-ok_hello.name"]
        assert [m["id"] for m in (await c.get("/api/mentions", params={"q": "out"})).json()] == ["Outputs today"]
        assert (await c.get("/api/mentions", params={"kind": "voice"})).json() == []
        assert len((await c.get("/api/mentions", params={"q": "sta"})).json()) == 2        # the start of a kind lists them all
