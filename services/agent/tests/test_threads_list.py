"""Plan chat-history 1.1: the thread list's archived filter (live, archived or both), and the count that matches the
list for the same filters."""

from __future__ import annotations

import time

from agent.store import Store


def _store(tmp_path) -> Store:
    """Six chats: two archived; environments grants, default (none) and gone; one message mentions "pelican"."""
    s = Store(tmp_path / "agent.db")
    rows = [("a1", "grants", False), ("a2", "grants", True), ("b1", None, False), ("b2", None, True),
            ("c1", "gone", False), ("pelican notes", "grants", False)]
    for title, env, archived in rows:
        t = s.create_thread(title, None, "manual", {"environment": env} if env else {})
        if archived:
            s.update_thread(t["id"], archived=True)
        time.sleep(0.002)
    s.append(s.threads(q="b1")[0]["id"], "user", {"text": "a word about a pelican"})
    return s


def titles(rows):
    return [t["title"] for t in rows]


def test_archived_false_true_and_both(tmp_path):
    s = _store(tmp_path)
    assert titles(s.threads(sort="title")) == ["a1", "b1", "c1", "pelican notes"]
    assert titles(s.threads(archived=True, sort="title")) == ["a2", "b2"]
    both = s.threads(archived=None, sort="title")
    assert titles(both) == ["a1", "a2", "b1", "b2", "c1", "pelican notes"]
    assert {t["title"]: t["archived"] for t in both}["a2"] is True                     # each row says which it is


def test_filters_together_and_offset(tmp_path):
    s = _store(tmp_path)
    assert titles(s.threads(q="pelican", archived=None, sort="title")) == ["b1", "pelican notes"]   # title or message
    assert titles(s.threads(environment=["grants"], archived=None, sort="title")) == ["a1", "a2", "pelican notes"]
    assert titles(s.threads(environment=["default"], archived=True)) == ["b2"]
    assert titles(s.threads(archived=None, sort="title", limit=2, offset=2)) == ["b1", "b2"]
    assert titles(s.threads(archived=None, sort="title", limit=10, offset=5)) == ["pelican notes"]


def test_count_matches_the_list(tmp_path):
    s = _store(tmp_path)
    for kw in [{}, {"archived": True}, {"archived": None}, {"q": "pelican"}, {"q": "pelican", "archived": None},
               {"environment": ["grants"]}, {"environment": ["grants", "gone"], "archived": None},
               {"environment": ["default"], "archived": True}, {"q": "nothing like it"}]:
        assert s.count(**kw) == len(s.threads(limit=1000, **kw)), kw


def test_groups_both(tmp_path):
    s = _store(tmp_path)
    assert {g["environment"]: g["count"] for g in s.groups()} == {"grants": 2, "default": 1, "gone": 1}
    assert {g["environment"]: g["count"] for g in s.groups(archived=True)} == {"grants": 1, "default": 1}
    assert {g["environment"]: g["count"] for g in s.groups(archived=None)} == {"grants": 3, "default": 2, "gone": 1}


async def test_routes(env):
    c = env.client
    ids = []
    for title, e in [("one", "grants"), ("two", None), ("three", "grants")]:
        r = await c.post("/v1/threads", json={"title": title, "settings": {"environment": e} if e else {}})
        ids.append(r.json()["id"])
    assert (await c.patch(f"/v1/threads/{ids[2]}", json={"archived": True})).status_code == 200

    async def names(**params):
        r = await c.get("/v1/threads", params={"sort": "title", **params})
        assert r.status_code == 200, r.text
        return titles(r.json())

    assert await names() == ["one", "two"]                                                       # default: live only
    assert await names(archived="false") == ["one", "two"]
    assert await names(archived="true") == ["three"]
    assert await names(archived="all") == ["one", "three", "two"]
    assert await names(archived="all", environment="grants") == ["one", "three"]
    assert await names(archived="all", limit=1, offset=1) == ["three"]
    assert (await c.get("/v1/threads", params={"archived": "maybe"})).status_code == 422

    async def count(**params):
        r = await c.get("/v1/threads/count", params=params)
        assert r.status_code == 200, r.text
        return r.json()["count"]

    assert await count() == 2 and await count(archived="true") == 1 and await count(archived="all") == 3
    assert await count(archived="all", environment="grants") == 2
    assert await count(q="thr") == 0 and await count(q="thr", archived="all") == 1

    groups = (await c.get("/v1/threads/groups", params={"archived": "all"})).json()
    assert {g["environment"]: g["count"] for g in groups} == {"grants": 2, "default": 1}
