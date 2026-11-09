"""Plan projects 2.1: a call naming several environments (`origin.environments`, primary first: a project chat's) uses
all their folders, each at the highest level any of them gives it; the folders allowed in the chat stay at Read, and the
skills of every environment's folders are listed. Projects' own environments are left out of the lists."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import folders as folders_mod


def origin(**o):
    return {"X-GAIFA-Origin": json.dumps({"service": "agent", "thread": "t1", "turn": 1, "tool_call": "c1", **o})}


def lim(client, tool, o, **args):
    r = client.post("/v1/limits", json={"tool": tool, "arguments": args, "origin": o})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture
def notes(tmp_path: Path) -> Path:
    n = tmp_path / "notes"
    (n / ".claude" / "skills" / "cite").mkdir(parents=True)
    (n / ".claude" / "skills" / "cite" / "SKILL.md").write_text("---\nname: cite\ndescription: How to cite\n---\nCite well.\n")
    (n / "todo.md").write_text("- write\n")
    return n


@pytest.fixture
def setup(client, repo, notes):
    """Grants: proj at Read; Thesis: proj at Edit and notes at Read; the project's own: notes at Edit."""
    client.post("/v1/environments", json={"name": "Grants"})
    client.post("/v1/environments", json={"name": "Thesis"})
    client.post("/v1/environments/grants/folders", json={"path": str(repo)})
    client.post("/v1/environments/thesis/folders", json={"path": str(repo), "level": "edit"})
    client.post("/v1/environments/thesis/folders", json={"path": str(notes)})
    r = client.post("/v1/environments", json={"name": "Thesis (project)", "id": "proj-abc", "project": "p_abc"})
    assert r.status_code == 200 and r.json()["project"] == "p_abc"
    client.post("/v1/environments/proj-abc/folders", json={"path": str(notes), "level": "edit"})
    return {"repo": repo, "notes": notes}


def test_the_union_and_the_highest_level(client, setup):
    listed = client.get("/v1/folders", headers=origin(environments=["grants", "thesis"])).json()
    levels = {f["id"]: f["level"] for f in listed["folders"]}
    assert levels == {"proj": "edit", "notes": "read"}                       # proj: Read in Grants, Edit in Thesis
    assert listed["environment"]["id"] == "grants"                           # the primary
    assert [e["id"] for e in listed["environments"]] == ["grants", "thesis"]
    three = client.get("/v1/folders", headers=origin(environments=["grants", "thesis", "proj-abc"])).json()
    assert {f["id"]: f["level"] for f in three["folders"]} == {"proj": "edit", "notes": "edit"}
    only = client.get("/v1/folders", headers=origin(environment="grants")).json()   # one environment works as before
    assert {f["id"]: f["level"] for f in only["folders"]} == {"proj": "read"} and "environments" not in only
    both = client.get("/v1/folders", headers=origin(environment="thesis", environments=["grants"])).json()
    assert {f["id"] for f in both["folders"]} == {"proj"}                    # environments wins over environment
    assert {f["id"] for f in client.get("/v1/folders", headers=origin(environments=["grants", "gone"])).json()["folders"]} == {"proj"}


def test_an_edit_allowed_through_the_second_environment(client, setup):
    o = {"environments": ["grants", "thesis"], "thread": "t1"}
    assert not lim(client, "edit", o, folder="proj", path="pkg/calc.py", old="a - b", new="a + b").get("refuse")
    assert lim(client, "edit", {"environment": "grants"}, folder="proj", path="pkg/calc.py", old="a - b",
               new="a + b")["refuse"]["code"] == "level"
    r = client.post("/v1/edit", json={"folder": "proj", "path": "pkg/calc.py", "old": "return a - b", "new": "return a + b"},
                    headers=origin(environments=["grants", "thesis"]))
    assert r.status_code == 200, r.text
    assert "return a + b" in (setup["repo"] / "pkg" / "calc.py").read_text()
    r = client.post("/v1/edit", json={"folder": "notes", "path": "todo.md", "old": "write", "new": "draft"},
                    headers=origin(environments=["grants", "thesis"]))
    assert r.status_code == 403 or r.json().get("code") == "level", r.text           # notes is Read in both


def test_a_run_refused_when_no_environment_gives_run(client, setup):
    o = {"environments": ["grants", "thesis", "proj-abc"]}
    assert lim(client, "run", o, folder="proj", command="pytest")["refuse"]["code"] == "level"
    client.patch("/v1/environments/grants/folders/proj", json={"level": "run"})
    assert not lim(client, "run", o, folder="proj", command="pytest").get("refuse")


def test_grants_stay_at_read(client, setup, tmp_path, monkeypatch):
    monkeypatch.setattr(folders_mod, "grant_roots", lambda: [tmp_path])
    extra = tmp_path / "extra"
    extra.mkdir()
    (extra / "a.txt").write_text("a\n")
    o = {"environments": ["grants", "thesis"], "folders": [{"path": str(extra), "level": "edit"}]}
    listed = client.get("/v1/folders", headers=origin(**o)).json()
    granted = [f for f in listed["folders"] if f.get("granted")]
    assert [(Path(f["path"]).name, f["level"]) for f in granted] == [("extra", "read")]
    assert lim(client, "write", o, folder=granted[0]["id"], path="a.txt", content="b")["refuse"]["code"] == "level"
    o2 = {"environments": ["grants", "thesis"], "folders": [{"path": str(setup["repo"]), "level": "read"}]}
    assert [f["level"] for f in client.get("/v1/folders", headers=origin(**o2)).json()["folders"] if f["id"] == "proj"] == ["edit"]


def test_skills_across_every_environment(client, setup):
    ids = {s["id"] for s in client.get("/v1/skills", headers=origin(environments=["grants", "thesis"])).json()["skills"]}
    assert "notes:cite" in ids
    assert "notes:cite" not in {s["id"] for s in client.get("/v1/skills", headers=origin(environment="grants")).json()["skills"]}
    r = client.post("/v1/skills/read", json={"id": "notes:cite"}, headers=origin(environments=["grants", "proj-abc"]))
    assert r.status_code == 200 and r.json()["text"].strip() == "Cite well."


def test_project_environments_hidden_from_the_list(client, setup):
    listed = [e["id"] for e in client.get("/v1/environments").json()["environments"]]
    assert "proj-abc" not in listed and {"grants", "thesis"} <= set(listed)
    assert "proj-abc" in [e["id"] for e in client.get("/v1/environments", params={"all": 1}).json()["environments"]]
    assert client.get("/v1/environments/proj-abc").json()["project"] == "p_abc"
    assert client.delete("/v1/environments/proj-abc").json() == {"deleted": "proj-abc"}
    assert "proj-abc" not in [e["id"] for e in client.get("/v1/environments", params={"all": 1}).json()["environments"]]
