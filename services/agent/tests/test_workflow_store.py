"""Plan agent-workflows 1.1: sub-agents in the store: the marker against a fork, the tree, the list filters, archive and
delete with the parent."""

from __future__ import annotations


def _child(store, parent, root=None, label="Reader", **kw):
    root = root or parent
    spawn = {"root": root, "parent": parent, "label": label, "by": "agent", "depth": 1, **kw}
    return store.create_thread(label, None, "manual", {"spawn": spawn}, parent_id=parent)


async def test_children_and_the_tree(env):
    store = env.agent.store
    root = store.create_thread("Main", None, "auto")
    a = _child(store, root["id"], label="Folders")
    b = _child(store, root["id"], label="Pages", seen=False, write=True)
    assert [c["id"] for c in store.children(root["id"])] == [a["id"], b["id"]]
    assert store.thread(root["id"])["children"] == 2 and store.thread(a["id"])["spawn"]["parent"] == root["id"]
    assert store.root_of(a["id"]) == root["id"] and store.root_of(root["id"]) == root["id"]
    r = await env.client.get(f"/v1/threads/{a['id']}/tree")         # asked from a child: the same workflow
    assert r.status_code == 200
    t = r.json()
    assert t["root"]["id"] == root["id"] and t["root"]["children"] == 2
    assert [(n["label"], n["parent"], n["seen"], n["write"]) for n in t["children"]] == [
        ("Folders", root["id"], True, False), ("Pages", root["id"], False, True)]
    assert (await env.client.get("/v1/threads/t_nope/tree")).status_code == 404


async def test_a_fork_is_not_a_sub_agent(env):
    store = env.agent.store
    root = store.create_thread("Main", None, "auto")
    child = _child(store, root["id"])
    store.append(child["id"], "user", {"text": "read the folder"})
    branch = store.fork(child["id"], 1)
    assert branch["parent_id"] == child["id"] and "spawn" not in branch["settings"] and "spawn" not in branch
    assert store.thread(child["id"])["children"] == 0                 # a branch isn't counted as its child
    plain = store.fork(root["id"], 0)
    assert store.tree(plain["id"])["children"] == []


async def test_lists_leave_sub_agents_out(env):
    store = env.agent.store
    root = store.create_thread("Main chat", None, "auto")
    child = _child(store, root["id"], label="Main helper")
    ids = [t["id"] for t in (await env.client.get("/v1/threads")).json()]
    assert root["id"] in ids and child["id"] not in ids
    listed = next(t for t in (await env.client.get("/v1/threads")).json() if t["id"] == root["id"])
    assert listed["children"] == 1
    assert child["id"] in [t["id"] for t in (await env.client.get("/v1/threads?children=true")).json()]
    found = (await env.client.get("/v1/threads?q=helper")).json()     # a search finds them, with their parent
    assert [t["id"] for t in found] == [child["id"]] and found[0]["spawn"]["parent"] == root["id"]
    assert (await env.client.get("/v1/threads/count")).json()["count"] == 1
    assert (await env.client.get("/v1/threads/count?children=true")).json()["count"] == 2
    assert [g["count"] for g in (await env.client.get("/v1/threads/groups")).json()] == [1]


async def test_archive_and_delete_go_with_the_parent(env):
    store = env.agent.store
    root = store.create_thread("Main", None, "auto")
    a, b = _child(store, root["id"]), _child(store, root["id"], label="Two")
    r = await env.client.patch(f"/v1/threads/{root['id']}", json={"archived": True})
    assert r.status_code == 200
    assert store.thread(a["id"])["archived"] and store.thread(b["id"])["archived"]
    await env.client.patch(f"/v1/threads/{root['id']}", json={"archived": False})
    assert not store.thread(a["id"])["archived"]
    await env.client.patch(f"/v1/threads/{a['id']}", json={"archived": True})     # a child alone
    assert store.thread(a["id"])["archived"] and not store.thread(root["id"])["archived"]
    r = await env.client.delete(f"/v1/threads/{root['id']}")
    assert r.status_code == 200 and sorted(r.json()["children"]) == sorted([a["id"], b["id"]])
    assert store.thread(a["id"]) is None and store.thread(b["id"]) is None
    assert {a["id"], b["id"], root["id"]} <= set(env.hub.ended_grants)


async def test_a_child_left_running_resumes(env):
    store = env.agent.store
    root = store.create_thread("Main", None, "auto")
    child = _child(store, root["id"])
    store.append(child["id"], "user", {"text": "go"})
    store.update_thread(child["id"], state="running")
    assert await env.agent.resume_all() == 1
    assert await env.settle(child["id"]) == "idle"
