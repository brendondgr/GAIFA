"""skill-sources 2.1: every coding agent's skills and instruction files in the chat's workspace folders."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import folders as folders_mod


def origin(**o):
    return {"X-GAIFA-Origin": json.dumps(o)}


def skill(d: Path, name: str, desc: str = "Does a thing", body: str = "Steps.", extra: str = "") -> Path:
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {desc}\n{extra}---\n{body}\n")
    return d


@pytest.fixture
def proj(repo: Path, tmp_path: Path) -> Path:
    skill(repo / ".claude" / "skills" / "plan", "plan", "Write plans", "Plan body.")
    skill(repo / ".agents" / "skills" / "plan", "plan", "Write plans", "Plan body.")         # the same skill again
    skill(repo / ".claude" / "skills" / "deploy", "deploy", "Deploy the app", "Claude's way.")
    skill(repo / ".codex" / "skills" / "deploy", "deploy", "Deploy the app", "Codex's way.")   # same name, other text
    skill(repo / ".cursor" / "skills" / "hidden-one", "hidden-one", "Only by slash", extra="disable-model-invocation: true\n")
    for agent in (".claude", ".agents"):
        refs = repo / agent / "skills" / "plan" / "references"
        refs.mkdir()
        (refs / "format.md").write_text("The format.")
        (repo / agent / "skills" / "plan" / "secrets.md").write_text("shh")
    outside = skill(tmp_path / "elsewhere" / "evil", "evil", "Outside")
    (repo / ".claude" / "skills" / "evil").symlink_to(outside)
    (repo / "AGENTS.md").write_text("# Rules\n\nBe kind.\n")
    (repo / "CLAUDE.md").write_text("@AGENTS.md\n")
    (repo / ".cursor" / "rules").mkdir(parents=True)
    (repo / ".cursor" / "rules" / "always.mdc").write_text("---\ndescription: x\nalwaysApply: true\n---\nAlways this.\n")
    (repo / ".cursor" / "rules" / "sometimes.mdc").write_text("---\ndescription: y\nalwaysApply: false\n---\nSometimes.\n")
    return repo


def test_a_folders_skills_are_listed_once_each(client, proj):
    client.post("/v1/environments/default/folders", json={"path": str(proj)})
    out = client.get("/v1/skills", headers=origin(environment="default")).json()
    by = {s["id"]: s for s in out["skills"]}
    assert set(by) == {"proj:plan", "proj:claude.deploy", "proj:codex.deploy", "proj:hidden-one"}
    assert by["proj:plan"]["found_in"] == [".agents/skills/plan/SKILL.md", ".claude/skills/plan/SKILL.md"]
    assert by["proj:plan"]["description"] == "Write plans" and by["proj:plan"]["folder"]["id"] == "proj"
    assert by["proj:hidden-one"]["model_invocable"] is False and by["proj:plan"]["model_invocable"] is True
    assert "evil" not in json.dumps(out["skills"])                                    # a symlink out is skipped
    assert [(i["id"], i["also"]) for i in out["instructions"]] == [("proj:AGENTS.md", ["CLAUDE.md"]),
                                                                   ("proj:.cursor/rules/always.mdc", [])]


def test_reading_a_skill_its_files_and_instructions(client, proj):
    client.post("/v1/environments/default/folders", json={"path": str(proj)})
    read = lambda i: client.post("/v1/skills/read", json={"id": i})  # noqa: E731
    r = read("proj:plan").json()
    assert r["kind"] == "skill" and r["text"].strip() == "Plan body." and [f["path"] for f in r["files"]] == ["references/format.md"]
    assert read("proj:plan/references/format.md").json() == {"id": "proj:plan/references/format.md", "kind": "file", "text": "The format."}
    assert read("proj:plan/secrets.md").json()["code"] == "secret_file"
    assert read("proj:codex.deploy").json()["text"].strip() == "Codex's way."
    assert read("proj:AGENTS.md").json()["text"].startswith("# Rules")
    assert read("proj:CLAUDE.md").json()["kind"] == "instructions"
    assert read("proj:nope").status_code == 404 and read("proj:plan/../../.env").status_code in (403, 404)
    assert read("other:plan").json()["code"] == "unknown_folder" and read("plan").status_code == 404


def test_the_same_text_with_other_files_is_another_skill(client, proj):
    (proj / ".agents" / "skills" / "plan" / "references" / "extra.md").write_text("More.")
    client.post("/v1/environments/default/folders", json={"path": str(proj)})
    ids = {s["id"] for s in client.get("/v1/skills").json()["skills"]}
    assert {"proj:agents.plan", "proj:claude.plan"} <= ids and "proj:plan" not in ids


def test_no_folders_no_skills(client, proj):
    client.post("/v1/environments/default/folders", json={"path": str(proj)})
    assert client.get("/v1/skills", headers=origin(environment="none")).json() == {"skills": [], "instructions": []}
    client.post("/v1/environments", json={"name": "Empty"})
    assert client.get("/v1/skills?environment=empty").json() == {"skills": [], "instructions": []}


def test_a_folder_allowed_in_the_chat_counts(client, proj, tmp_path, monkeypatch):
    monkeypatch.setattr(folders_mod, "grant_roots", lambda: [tmp_path])
    out = client.get("/v1/skills", headers=origin(environment="none", folders=[{"path": str(proj)}])).json()
    assert "proj:plan" in {s["id"] for s in out["skills"]}


def test_a_changed_skill_is_read_again(client, proj):
    client.post("/v1/environments/default/folders", json={"path": str(proj)})
    first = {s["id"]: s for s in client.get("/v1/skills").json()["skills"]}
    skill(proj / ".claude" / "skills" / "plan", "plan", "Write better plans", "Plan body v2.")
    second = {s["id"]: s for s in client.get("/v1/skills").json()["skills"]}
    assert first["proj:plan"]["description"] == "Write plans"
    assert {second[k]["description"] for k in second if k.endswith("plan")} >= {"Write better plans"}
