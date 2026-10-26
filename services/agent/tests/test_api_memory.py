"""structured-memory 1.2: the memory routes over the app."""

from __future__ import annotations


async def test_entities_facts_and_undo_over_http(env):
    c = env.client
    g = (await c.post("/v1/memory/entities", json={"kind": "projects", "name": "AIHub",
                                                   "anchors": [{"kind": "folder", "value": "/home/u/Agents/GAIFA"}]})).json()
    assert g["path"] == "projects/AIHub" and g["anchors"] == [{"kind": "folder", "value": "/home/u/Agents/GAIFA"}]
    assert (await c.post("/v1/memory/entities", json={"kind": "project", "name": "aihub"})).json()["code"] == "exists"
    f = (await c.post("/v1/memory/facts", json={"text": "Mods use ports 5100-5199", "about": ["AIHub"]})).status_code
    assert f == 201
    r = (await c.patch(f"/v1/memory/entities/{g['id']}", json={"name": "GAIFA"})).json()
    assert r["aliases"] == ["AIHub"]
    view = (await c.get("/v1/memory/entities/projects/GAIFA")).json()
    assert view["id"] == g["id"] and [x["text"] for x in view["facts"]] == ["Mods use ports 5100-5199"]
    assert view["log"][0]["summary"] == "AIHub: renamed AIHub → GAIFA"
    assert (await c.get("/v1/memory/entities/aihub")).json()["id"] == g["id"]
    undo = await c.post(f"/v1/memory/undo/{view['log'][0]['id']}")
    assert undo.status_code == 200 and (await c.get(f"/v1/memory/entities/{g['id']}")).json()["name"] == "AIHub"
    tree = (await c.get("/v1/memory/tree")).json()
    assert [k["kind"] for k in tree["kinds"]][:2] == ["user", "project"]
    assert (await c.get("/v1/memory/entities/nope")).status_code == 404


async def test_fact_states_and_forget(env):
    c = env.client
    p = (await c.post("/v1/memory/facts", json={"text": "Likes pastel colors", "source": "inferred", "kind": "preference"})).json()
    assert p["state"] == "proposed"
    assert [x["id"] for x in (await c.get("/v1/memory/facts?state=proposed")).json()] == [p["id"]]
    a = (await c.patch(f"/v1/memory/facts/{p['id']}", json={"state": "active", "text": "Likes pastel colours"})).json()
    assert a["state"] == "active" and a["text"] == "Likes pastel colours" and a["current"]
    n = (await c.post("/v1/memory/facts", json={"text": "Likes bold colours", "replaces": p["id"], "valid_from": "2026-10-26"})).json()
    assert (await c.get(f"/v1/memory/facts?entity=user&current=true")).json()[0]["id"] == n["id"]
    bad = await c.post("/v1/memory/facts", json={"text": "x", "valid_from": "yesterday"})
    assert bad.status_code == 422 and bad.json()["code"] == "bad_date"
    assert (await c.delete(f"/v1/memory/facts/{p['id']}")).json() == {"forgotten": p["id"]}
    assert (await c.patch(f"/v1/memory/facts/{p['id']}", json={"state": "active"})).status_code == 404


async def test_merge_over_http(env):
    c = env.client
    a = (await c.post("/v1/memory/entities", json={"kind": "person", "name": "Ana"})).json()
    b = (await c.post("/v1/memory/entities", json={"kind": "person", "name": "Ana B."})).json()
    m = (await c.post(f"/v1/memory/entities/{b['id']}/merge", json={"into": a["id"]})).json()
    assert m["aliases"] == ["Ana B."]
    assert (await c.post(f"/v1/memory/entities/{a['id']}/merge", json={"into": a["id"]})).json()["code"] == "bad_merge"
