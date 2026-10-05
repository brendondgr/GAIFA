"""5.3: the load rule as a pure function: enough room, a covering plan, not enough, and who may never be unloaded."""

from __future__ import annotations

from utils.memory.planner import Candidate, describe, make_plan

GB = 1024**3


def cand(id: str, **kw) -> Candidate:
    base = dict(name=id.upper(), load="loaded", up=True, busy=False, in_flight=0, auto_unload=True, unloadable=True,
                priority=100, idle_s=60.0, used_bytes=10 * GB, estimate_bytes=10 * GB)
    return Candidate(id=id, **{**base, **kw})


def ids(plan) -> list[str]:
    return [u["id"] for u in plan["unload"]]


def test_enough_room():
    p = make_plan("gen3d", 30 * GB, 40 * GB, [cand("tts")], set())
    assert p == {"service": "gen3d", "needs_bytes": 30 * GB, "available_bytes": 40 * GB, "unload": [], "enough": True}


def test_covering_plan_by_priority_then_idle():
    cs = [
        cand("comfy", priority=0, idle_s=100, used_bytes=24 * GB),
        cand("tts", priority=1, idle_s=900, used_bytes=9 * GB),
        cand("a", priority=5, idle_s=10, used_bytes=5 * GB),
        cand("b", priority=5, idle_s=500, used_bytes=5 * GB),  # same priority, idle longer: first
    ]
    p = make_plan("gen3d", 52 * GB, 31 * GB, cs, set())
    assert ids(p) == ["comfy"] and p["enough"]  # 31 + 24 ≥ 52: stop as soon as it's covered
    assert p["unload"][0] == {"id": "comfy", "frees_bytes": 24 * GB, "reason": "priority 0, idle 1m"}
    p = make_plan("gen3d", 68 * GB, 31 * GB, cs, set())
    assert ids(p) == ["comfy", "tts", "b"] and p["enough"]  # 31 + 24 + 9 + 5


def test_not_enough():
    p = make_plan("gen3d", 100 * GB, 31 * GB, [cand("tts", used_bytes=9 * GB)], set())
    assert ids(p) == ["tts"] and not p["enough"]
    assert describe(p, "3D Generate") == "Loading 3D Generate needs ~100.0 GB, 31.0 GB available. Even unloading tts isn't enough."
    p = make_plan("gen3d", 100 * GB, -5 * GB, [], set())  # reserve bigger than what's free
    assert p["available_bytes"] == 0 and not p["enough"]
    assert describe(p, "3D Generate").endswith("no idle mod can be unloaded to make room.")


def test_who_is_never_a_candidate():
    cs = [
        cand("lcpp", used_bytes=50 * GB),  # never_unload
        cand("busy", busy=True), cand("flight", in_flight=1), cand("manual", auto_unload=False),
        cand("cold", load="unloaded"), cand("loading", load="loading"), cand("down", up=False),
        cand("noop", unloadable=False), cand("gen3d", used_bytes=99 * GB),  # the target itself
        cand("ok", used_bytes=3 * GB),
    ]
    p = make_plan("gen3d", 40 * GB, 1 * GB, cs, {"lcpp"})
    assert ids(p) == ["ok"] and not p["enough"]


def test_unmeasured_mods_free_their_estimate():
    p = make_plan("x", 20 * GB, 5 * GB, [cand("a", used_bytes=0, estimate_bytes=16 * GB), cand("b", used_bytes=0, estimate_bytes=None)], set())
    assert ids(p) == ["a"] and p["unload"][0]["frees_bytes"] == 16 * GB and p["enough"]
