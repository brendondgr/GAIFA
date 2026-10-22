"""Plan 41.1: threads per environment (`settings.environment`, none is Default), three orders, paging, and the
groups the chat list draws its sections from."""

from __future__ import annotations

import time

from agent.store import Store


def _store(tmp_path) -> Store:
    s = Store(tmp_path / "agent.db")
    for title, env in [("beta", "grants"), ("Alpha", "grants"), ("gamma", None), ("delta", "default"), ("epsilon", "gone")]:
        s.create_thread(title, None, "manual", {"environment": env} if env else {})
        time.sleep(0.002)
    return s


def test_threads_by_environment_and_order(tmp_path):
    s = _store(tmp_path)
    assert [t["title"] for t in s.threads(environment=["grants"])] == ["Alpha", "beta"]        # newest first
    assert [t["title"] for t in s.threads(environment=["grants"], sort="title")] == ["Alpha", "beta"]
    assert [t["title"] for t in s.threads(environment=["default"])] == ["delta", "gamma"]      # none counts as Default
    assert {t["title"] for t in s.threads(environment=["default", "gone"])} == {"delta", "gamma", "epsilon"}
    assert [t["title"] for t in s.threads(sort="created", limit=2)] == ["epsilon", "delta"]
    assert [t["title"] for t in s.threads(sort="created", limit=2, offset=2)] == ["gamma", "Alpha"]
    assert [t["title"] for t in s.threads(sort="title")][:2] == ["Alpha", "beta"]              # case-insensitive
    assert len(s.threads()) == 5                                                                  # unchanged without filters


def test_groups(tmp_path):
    s = _store(tmp_path)
    tid = s.threads(environment=["grants"])[0]["id"]
    s.update_thread(tid, state="running")
    rows = {g["environment"]: g for g in s.groups()}
    assert {k: v["count"] for k, v in rows.items()} == {"grants": 2, "default": 2, "gone": 1}
    assert rows["grants"]["running"] == 1 and rows["default"]["running"] == 0
    assert rows["grants"]["updated"] == max(t["updated"] for t in s.threads(environment=["grants"]))
    s.update_thread(tid, archived=True)
    assert {g["environment"]: g["count"] for g in s.groups()}["grants"] == 1                    # archived kept apart
    assert s.groups(archived=True) == [{"environment": "grants", "count": 1, "updated": s.thread(tid)["updated"], "running": 1}]


async def test_routes(env):
    c = env.client
    for title, e in [("one", "grants"), ("two", None)]:
        r = await c.post("/v1/threads", json={"title": title, "settings": {"environment": e} if e else {}})
        assert r.status_code == 201
    groups = (await c.get("/v1/threads/groups")).json()
    assert {g["environment"]: g["count"] for g in groups} == {"grants": 1, "default": 1}
    assert [t["title"] for t in (await c.get("/v1/threads", params={"environment": "grants"})).json()] == ["one"]
    both = await c.get("/v1/threads", params={"environment": "default,grants", "sort": "title"})
    assert [t["title"] for t in both.json()] == ["one", "two"]
    assert (await c.get("/v1/threads", params={"sort": "nope"})).status_code == 422
