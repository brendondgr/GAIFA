"""Folders, levels and the hard limits on paths (plan 27.1)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from folders import LEVELS, Refused


def add(client, path, **kw):
    r = client.post("/v1/folders", json={"path": str(path), **kw})
    assert r.status_code == 200, r.text
    return r.json()


def test_new_folders_start_at_read_and_each_level_can_be_set(client, repo):
    f = add(client, repo)
    assert f["level"] == "read" and f["id"] == "proj" and not f["allow_bypass"]
    for level in LEVELS:
        r = client.patch(f"/v1/folders/{f['id']}", json={"level": level})
        assert r.status_code == 200 and r.json()["level"] == level
    assert client.get("/v1/folders").json()["folders"][0]["level"] == "run_net"
    assert client.patch("/v1/folders/proj", json={"level": "root"}).status_code == 422
    assert client.delete("/v1/folders/proj").json() == {"removed": "proj"}
    assert client.get("/v1/folders").json()["folders"] == []


def test_adding_a_folder_twice_or_a_file_or_home_is_refused(client, repo):
    add(client, repo)
    assert client.post("/v1/folders", json={"path": str(repo)}).json()["code"] == "exists"
    assert client.post("/v1/folders", json={"path": str(repo / "README.md")}).json()["code"] == "not_a_folder"
    assert client.post("/v1/folders", json={"path": str(Path.home())}).json()["code"] == "too_broad"


def test_level_caps_what_can_happen(ctx, repo):
    f = ctx.folders.add(str(repo))
    with pytest.raises(Refused) as e:
        ctx.folders.need(f, "edit", "editing a file")
    assert e.value.code == "level" and "Workspace page" in e.value.fix
    f = ctx.folders.update(f.id, level="edit")
    ctx.folders.need(f, "edit", "editing")
    with pytest.raises(Refused):
        ctx.folders.need(ctx.folders.get(f.id), "run", "running a command")
    ctx.folders.update(f.id, level="run")
    ctx.folders.need(ctx.folders.get(f.id), "run", "running")
    with pytest.raises(Refused):
        ctx.folders.need(ctx.folders.get(f.id), "run_net", "a command with network")


@pytest.mark.parametrize("rel,code", [
    ("../outside.txt", "outside_folder"),
    ("pkg/../../outside.txt", "outside_folder"),
    ("/etc/passwd", "outside_folder"),
    ("link_out/passwd", "symlink_out"),
    ("evil", "symlink_out"),
])
def test_escapes_are_refused(ctx, repo, rel, code):
    (repo.parent / "outside.txt").write_text("no")
    os.symlink("/etc", repo / "link_out")
    os.symlink(repo.parent / "outside.txt", repo / "evil")
    f = ctx.folders.add(str(repo), level="edit")
    with pytest.raises(Refused) as e:
        ctx.folders.resolve(f, rel)
    assert e.value.code == code


def test_absolute_paths_inside_and_symlinks_inside_are_fine(ctx, repo):
    os.symlink(repo / "pkg" / "calc.py", repo / "calc_link.py")
    f = ctx.folders.add(str(repo))
    p, rel = ctx.folders.resolve(f, str(repo / "pkg" / "calc.py"))
    assert rel == "pkg/calc.py" and p == repo / "pkg" / "calc.py"
    assert ctx.folders.resolve(f, "calc_link.py")[1] == "pkg/calc.py"
    assert ctx.folders.resolve(f, ".")[1] == "."


@pytest.mark.parametrize("rel", [".env", "config/.env", "certs/server.pem", "id_rsa", "home/.ssh/id_ed25519.pub",
                                 "aws_credentials.json", "secrets.yaml", "secrets/db.txt"])
def test_secret_globs_unless_named(ctx, repo, rel):
    f = ctx.folders.add(str(repo), level="edit")
    with pytest.raises(Refused) as e:
        ctx.folders.resolve(f, rel)
    assert e.value.code == "secret_file"
    assert ctx.folders.resolve(f, rel, named=[Path(rel).name])[1] == rel
    assert ctx.folders.resolve(f, rel, named=[rel])[1] == rel


def test_not_secrets(ctx, repo):
    f = ctx.folders.add(str(repo))
    for rel in (".env.example", "environment.py", "pkg/ident.py", "README.md"):
        ctx.folders.resolve(f, rel)


def test_git_dir_written_only_by_the_git_tools(ctx, repo):
    f = ctx.folders.add(str(repo), level="edit")
    ctx.folders.resolve(f, ".git/HEAD")                               # reading is fine
    with pytest.raises(Refused) as e:
        ctx.folders.resolve(f, ".git/config", write=True)
    assert e.value.code == "git_dir"
    ctx.folders.resolve(f, ".git/index", write=True, git=True)


def test_skip_rules_size_and_binaries(ctx, repo):
    from folders import MAX_BYTES, skipped

    assert skipped("node_modules", True) and skipped(".venv", True) and skipped(".git", True)
    assert not skipped("node_modules", False) and not skipped("src", True)
    (repo / "big.log").write_text("x" * (MAX_BYTES + 1))
    f = ctx.folders.add(str(repo))
    with pytest.raises(Refused) as e:
        ctx.folders.resolve(f, "big.log", read_file=True)
    assert e.value.code == "too_large"
    ctx.folders.resolve(f, "big.log", read_file=True, named=["big.log"])
    with pytest.raises(Refused) as e:
        ctx.folders.resolve(f, "blob.bin", read_file=True)
    assert e.value.code == "binary"


def test_the_aihub_folder_and_models_stay_at_read(client, ctx, aihub):
    f = add(client, aihub)
    assert f["max_level"] == "read" and "AIHub" in f["capped"]
    r = client.patch(f"/v1/folders/{f['id']}", json={"level": "edit"})
    assert r.status_code == 422 and r.json()["code"] == "capped"
    assert client.post("/v1/folders", json={"path": str(aihub / "data" / "models"), "level": "edit"}).json()["code"] == "capped"
    sub = add(client, aihub / "utils")
    assert sub["max_level"] == "read"
    # a folder that contains AIHub keeps its level, but nothing inside AIHub can be written
    outer = add(client, aihub.parent, level="edit")
    assert outer["level"] == "edit"
    o = ctx.folders.get(outer["id"])
    ctx.folders.resolve(o, "proj_new.txt", write=True)
    with pytest.raises(Refused) as e:
        ctx.folders.resolve(o, "AIHub/utils/proxy.py", write=True)
    assert e.value.code == "protected"
    ctx.folders.resolve(o, "AIHub/utils/proxy.py")                    # reading it is fine


def test_a_stored_level_above_the_cap_reads_as_read(ctx, aihub):
    import json

    ctx.folders.file.parent.mkdir(parents=True, exist_ok=True)
    ctx.folders.file.write_text(json.dumps({"folders": [{"id": "hub", "path": str(aihub), "level": "run_net", "allow_bypass": True}]}))
    f = ctx.folders.get("hub")
    assert ctx.folders.level(f) == "read"
    pub = ctx.folders.public()[0]
    assert pub["level"] == "read" and pub["allow_bypass"] is False


def test_folders_are_found_by_id_path_or_name(ctx, repo):
    f = ctx.folders.add(str(repo), name="Calc")
    assert ctx.folders.get("proj").id == f.id
    assert ctx.folders.get(str(repo)).id == f.id
    assert ctx.folders.get("calc").id == f.id
    with pytest.raises(Refused) as e:
        ctx.folders.get("nope")
    assert e.value.code == "unknown_folder" and "proj" in e.value.detail
