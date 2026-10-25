"""Environments (plan 34): named sets of folders with their own levels, the migration from Phase 27's
folders.json, a call resolving within its chat's environment, and asking for a folder outside it."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import folders as folders_mod


def origin(**o):
    return {"X-GAIFA-Origin": json.dumps(o)}


@pytest.fixture
def home(tmp_path, monkeypatch):
    """tmp_path stands in for the user's home: the folders the agent may ask for are in it."""
    monkeypatch.setattr(folders_mod, "grant_roots", lambda: [tmp_path])
    return tmp_path


@pytest.fixture
def other(tmp_path):
    """A second project, outside every environment (the user's "~/Agents/Mycelium")."""
    m = tmp_path / "Mycelium"
    (m / "core").mkdir(parents=True)
    (m / "core" / "net.py").write_text("def grow():\n    return 'hyphae'\n")
    (m / ".env").write_text("KEY=1\n")
    return m


def envs(client):
    return {e["id"]: e for e in client.get("/v1/environments").json()["environments"]}


def test_phase27_folders_become_default_keeping_ids_and_levels(client, ctx, repo):
    legacy = ctx.folders.envs.legacy
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text(json.dumps({"folders": [{"id": "calc", "path": str(repo), "level": "edit", "allow_bypass": True, "name": "Calc"}]}))
    e = envs(client)
    assert list(e) == ["none", "default"] and e["default"]["name"] == "Default" and e["default"]["default"] is True
    f = e["default"]["folders"][0]
    assert (f["id"], f["level"], f["allow_bypass"], f["name"]) == ("calc", "edit", True, "Calc")
    assert ctx.folders.envs.file.exists() and json.loads(legacy.read_text())["folders"][0]["id"] == "calc"   # left as it was
    assert client.get("/v1/folders").json()["folders"][0]["id"] == "calc"         # the old route: Default's folders
    assert client.get("/v1/folders").json()["environment"] == {"id": "default", "name": "Default"}


def test_environments_crud(client):
    r = client.post("/v1/environments", json={"name": "Grants"})
    assert r.status_code == 200 and r.json()["id"] == "grants" and r.json()["folders"] == []
    assert client.post("/v1/environments", json={"name": "grants"}).json()["code"] == "exists"
    assert client.post("/v1/environments", json={"name": "  "}).status_code == 422
    assert client.put("/v1/environments/grants", json={"name": "Grant work"}).json()["name"] == "Grant work"
    assert client.get("/v1/environments/grants").json()["name"] == "Grant work"
    assert client.put("/v1/environments/default", json={"name": "Everyday"}).json()["name"] == "Everyday"
    assert client.delete("/v1/environments/default").json()["code"] == "default"
    assert client.delete("/v1/environments/grants").json() == {"deleted": "grants"}
    assert client.get("/v1/environments/grants").status_code == 404
    assert client.delete("/v1/environments/grants").status_code == 404
    assert list(envs(client)) == ["none", "default"]


def test_none_is_built_in_with_no_folders(client, home, repo, other):
    """Plan 42.5: None is listed first, can't be renamed, deleted or given folders, and a chat in it reads only what it
    was allowed (each folder asked for)."""
    client.post("/v1/environments/default/folders", json={"path": str(repo)})
    listed = envs(client)
    assert list(listed)[0] == "none" and listed["none"]["none"] is True and listed["none"]["folders"] == []
    assert listed["default"]["none"] is False
    for r in (client.put("/v1/environments/none", json={"name": "Nothing"}), client.delete("/v1/environments/none"),
              client.post("/v1/environments/none/folders", json={"path": str(other)})):
        assert r.status_code == 422 and r.json()["code"] == "none", r.text
    assert client.post("/v1/environments", json={"name": "none"}).json()["code"] == "exists"
    assert client.put("/v1/environments/default", json={"name": "None"}).json()["code"] == "exists"
    assert client.get("/v1/environments/none").json()["name"] == "None"
    read = client.post("/v1/read", json={"folder": "proj", "path": "README.md"}, headers=origin(thread="t1", environment="none"))
    assert read.status_code == 404 and read.json()["code"] == "unknown_folder"           # Default's folder isn't there
    out = limits(client, "read", {"folder": str(other), "path": "core/net.py"}, thread="t1", environment="none")
    assert out["ask_folder"]["environment"] == {"id": "none", "name": "None"}            # asked for, as anywhere
    out = limits(client, "read", {"folder": str(other), "path": "core/net.py"}, thread="t1", environment="none",
                 folders=[{"path": str(other), "level": "read"}])
    assert "refuse" not in out and out["level"] == "read"                                 # allowed in this chat
    assert client.get("/v1/folders?environment=none").json()["folders"] == []


def test_a_folders_level_is_per_environment_and_its_id_is_shared(client, repo, tmp_path):
    client.post("/v1/environments", json={"name": "Grants"})
    a = client.post("/v1/environments/default/folders", json={"path": str(repo)}).json()
    b = client.post("/v1/environments/grants/folders", json={"path": str(repo), "level": "run"}).json()
    assert a["id"] == b["id"] == "proj" and a["level"] == "read" and b["level"] == "run"
    assert client.post("/v1/environments/grants/folders", json={"path": str(repo)}).json()["code"] == "exists"
    other = tmp_path / "x" / "proj"
    other.mkdir(parents=True)
    c = client.post("/v1/environments/grants/folders", json={"path": str(other)}).json()
    assert c["id"] == "proj-2"                                      # a different folder never takes an id in use
    assert client.patch("/v1/environments/grants/folders/proj", json={"level": "edit"}).json()["level"] == "edit"
    assert envs(client)["default"]["folders"][0]["level"] == "read"
    assert client.delete("/v1/environments/grants/folders/proj").json() == {"removed": "proj"}
    assert [f["id"] for f in envs(client)["default"]["folders"]] == ["proj"]
    assert client.post("/v1/environments/nope/folders", json={"path": str(repo)}).status_code == 404
    for bad in ("/", str(Path.home()), str(repo / "README.md")):
        assert client.post("/v1/environments/grants/folders", json={"path": bad}).json()["code"] in ("too_broad", "not_a_folder")


def test_the_gaifa_folder_stays_at_read_in_every_environment(client, gaifa):
    client.post("/v1/environments", json={"name": "Grants"})
    for env in ("default", "grants"):
        assert client.post(f"/v1/environments/{env}/folders", json={"path": str(gaifa), "level": "edit"}).json()["code"] == "capped"
        f = client.post(f"/v1/environments/{env}/folders", json={"path": str(gaifa)}).json()
        assert f["max_level"] == "read" and f["capped"]
        assert client.patch(f"/v1/environments/{env}/folders/{f['id']}", json={"level": "run"}).json()["code"] == "capped"
    models = gaifa / "data" / "models"
    assert client.post("/v1/environments/grants/folders", json={"path": str(models), "level": "edit"}).json()["code"] == "capped"


def test_a_call_uses_only_its_chats_environment(client, repo, other):
    client.post("/v1/environments", json={"name": "Grants"})
    client.post("/v1/environments/default/folders", json={"path": str(repo)})
    client.post("/v1/environments/grants/folders", json={"path": str(other)})
    read = lambda env, folder, path: client.post("/v1/read", json={"folder": folder, "path": path},  # noqa: E731
                                                 headers=origin(thread="t1", **({"environment": env} if env else {})))
    assert read(None, "proj", "README.md").status_code == 200                  # no environment: Default
    assert read("grants", "mycelium", "core/net.py").status_code == 200
    r = read("grants", "proj", "README.md")
    assert r.status_code == 404 and r.json()["code"] == "unknown_folder" and "environment Grants" in r.json()["detail"]
    assert read("default", "mycelium", "core/net.py").json()["code"] == "unknown_folder"
    assert read("deleted-env", "proj", "README.md").status_code == 200         # a deleted environment: Default
    listed = client.get("/v1/folders", headers=origin(environment="grants")).json()
    assert [f["id"] for f in listed["folders"]] == ["mycelium"] and listed["environment"]["name"] == "Grants"
    assert [f["id"] for f in client.get("/v1/folders?environment=default").json()["folders"]] == ["proj"]


def limits(client, tool, args, **o):
    return client.post("/v1/limits", json={"tool": tool, "arguments": args, "origin": o}).json()


def test_a_folder_outside_the_environment_is_asked_for_not_refused(client, home, repo, other):
    client.post("/v1/environments/default/folders", json={"path": str(repo)})
    for tool, args in (("tree", {}), ("read", {"path": "core/net.py"}), ("search", {"query": "x"}), ("git", {"command": "status"})):
        out = limits(client, tool, {"folder": str(other) + "/", **args}, thread="t1")
        assert "refuse" not in out, out
        assert out["ask_folder"] == {"path": str(other), "level": "read", "max_level": "run_net",
                                     "environment": {"id": "default", "name": "Default"}}
        assert out["key"] == f"folder:{other}" and out["action"] == "read" and out["folder"] is None
    # once the hub passes it as allowed in this chat: an ordinary read, at Read
    out = limits(client, "read", {"folder": str(other), "path": "core/net.py"}, thread="t1", folders=[{"path": str(other), "level": "read"}])
    assert "ask_folder" not in out and "refuse" not in out and out["folder"] == "mycelium" and out["level"] == "read"
    # a name that isn't a path is still refused (the model can't ask for "mycelium" by name)
    assert limits(client, "read", {"folder": "mycelium", "path": "x"})["refuse"]["code"] == "unknown_folder"
    # editing or running there isn't asked for: it needs the environment at a higher level
    r = limits(client, "edit", {"folder": str(other), "path": "core/net.py", "old": "a", "new": "b"})
    assert r["refuse"]["code"] == "unknown_folder" and "Workspace page" in r["refuse"]["fix"]


def test_allowed_folders_are_read_only_and_checked_again(client, home, other):
    granted = [{"path": str(other), "level": "run_net"}]                       # whatever an origin says: Read
    out = limits(client, "edit", {"folder": str(other), "path": "core/net.py", "old": "hyphae", "new": "x"}, folders=granted)
    assert out["refuse"]["code"] == "level"
    run = limits(client, "run", {"folder": "mycelium", "command": "ls"}, folders=granted)
    assert run["refuse"]["code"] == "level"
    r = client.post("/v1/read", json={"folder": "mycelium", "path": "core/net.py"}, headers=origin(folders=granted))
    assert r.status_code == 200 and "hyphae" in r.json()
    assert client.post("/v1/read", json={"folder": "mycelium", "path": ".env"}, headers=origin(folders=granted)).json()["code"] == "secret_file"
    pub = client.get("/v1/folders", headers=origin(folders=granted)).json()["folders"]
    assert len(pub) == 1 and pub[0]["granted"] is True and pub[0]["max_level"] == "read"
    # a granted path that can't be asked for (here: outside the stand-in home) is ignored
    assert client.get("/v1/folders", headers=origin(folders=[{"path": "/usr"}])).json()["folders"] == []


def test_folders_that_are_never_asked_for(client, home, repo, other, tmp_path):
    hidden = tmp_path / ".ssh"
    hidden.mkdir()
    (tmp_path / "secrets").mkdir()
    link = tmp_path / "to-etc"
    link.symlink_to("/etc")
    client.post("/v1/environments/default/folders", json={"path": str(repo)})
    for path, code in ((str(hidden), "not_grantable"), (str(tmp_path / "secrets"), "not_grantable"),
                       (str(link), "not_grantable"), ("/etc", "not_grantable"), ("/", "too_broad"),
                       (str(tmp_path / "nope"), "not_found"), (str(other / "core" / "net.py"), "not_a_folder")):
        out = limits(client, "tree", {"folder": path})
        assert out.get("refuse", {}).get("code") == code, (path, out)
        assert "ask_folder" not in out
    inner = limits(client, "tree", {"folder": str(repo / "pkg")})              # inside a folder of the chat: say which
    assert inner["refuse"]["code"] == "inside_folder" and "folder='proj'" in inner["refuse"]["fix"] and "path='pkg'" in inner["refuse"]["fix"]


def test_undo_finds_a_folder_in_any_environment(client, repo):
    client.post("/v1/environments", json={"name": "Grants"})
    client.post("/v1/environments/grants/folders", json={"path": str(repo), "level": "edit"})
    h = origin(thread="t9", turn=1, environment="grants")
    r = client.post("/v1/edit", json={"folder": "proj", "path": "pkg/calc.py", "old": "a - b", "new": "a + b"}, headers=h)
    assert r.status_code == 200, r.text
    assert client.post("/v1/edit", json={"folder": "proj", "path": "pkg/calc.py", "old": "a + b", "new": "a"},
                       headers=origin(thread="t9", turn=1)).json()["code"] == "unknown_folder"     # not in Default
    u = client.post("/v1/checkpoints/t9/1/undo")
    assert u.status_code == 200 and u.json()["status"] == "undone"
    assert "a - b" in (repo / "pkg" / "calc.py").read_text()
