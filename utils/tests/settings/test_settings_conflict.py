"""settings-that-stick 2.1: merging a save with what is saved now: scalars, tables, reorders, and the 409."""

from __future__ import annotations

import tomllib

import httpx
import pytest

from utils.settings_merge import Conflict, merge_value, rebase
from utils.tests.settings.test_settings import _file, _hub


def test_merge_value():
    assert merge_value("x", 1, 1, 2) == 2                       # only the writer changed it
    assert merge_value("x", 3, 1, 1) == 3                       # only someone else did: theirs stays
    assert merge_value("x", 2, 1, 2) == 2                       # both the same
    with pytest.raises(Conflict) as e:
        merge_value("judge.threshold", 0.4, 0.35, 0.5)
    assert (e.value.field, e.value.current, e.value.yours) == ("judge.threshold", 0.4, 0.5)
    # lists: the writer's additions and removals over what is saved now
    assert merge_value("l", ["a", "c", "d"], ["a", "d"], ["d", "b"]) == ["c", "d", "b"]
    # a reorder nobody else touched keeps the writer's order
    assert merge_value("o", ["a", "b", "c"], ["a", "b", "c"], ["c", "a", "b"]) == ["c", "a", "b"]
    # tables, entry by entry (and nested)
    cur, base = {"a": True, "b": True, "n": {"x": 1, "y": 1}}, {"a": True, "b": False, "n": {"x": 1, "y": 0}}
    assert merge_value("t", cur, base, {"a": False, "b": False, "n": {"x": 2, "y": 0}}) == {"a": False, "b": True, "n": {"x": 2, "y": 1}}


def test_rebase_leaves_keys_without_base():
    cur = {"judge": {"allow_commands": ["a", "c"], "threshold": 0.4}}
    out = rebase(cur, {"judge": {"allow_commands": ["a", "b"], "threshold": 0.5}}, {"judge": {"allow_commands": ["a"]}})
    assert out == {"judge": {"allow_commands": ["a", "c", "b"], "threshold": 0.5}}


async def test_a_value_changed_on_both_sides_is_a_conflict(rig, serve):
    served = await _hub(rig, serve)
    async with httpx.AsyncClient(base_url=served.url) as c:
        assert (await c.put("/api/settings", json={"judge": {"threshold": 0.4}})).status_code == 200
        r = await c.put("/api/settings", json={"judge": {"threshold": 0.5}, "base": {"judge": {"threshold": 0.35}}})
        assert r.status_code == 409 and r.json()["code"] == "settings_conflict"
        assert r.json()["data"] == {"field": "judge.threshold", "current": 0.4, "yours": 0.5}
        assert tomllib.loads(_file(served))["agent"]["judge"]["threshold"] == 0.4
        # the same change on both sides is no conflict
        r = await c.put("/api/settings", json={"judge": {"threshold": 0.4}, "base": {"judge": {"threshold": 0.35}}})
        assert r.status_code == 200


async def test_a_mod_switch_saved_elsewhere_stays(rig, serve):
    served = await _hub(rig, serve)
    async with httpx.AsyncClient(base_url=served.url) as c:
        s = (await c.get("/api/settings")).json()
        nav0 = s["ui"]["nav"]
        assert (await c.put("/api/settings", json={"ui": {"nav": {**nav0, "folded": True}}})).status_code == 200
        r = await c.put("/api/settings", json={"ui": {"nav": {**nav0, "services": "counts"}}, "base": {"ui": {"nav": nav0}}})
        assert r.status_code == 200
        assert r.json()["settings"]["ui"]["nav"] == {**nav0, "folded": True, "services": "counts"}
