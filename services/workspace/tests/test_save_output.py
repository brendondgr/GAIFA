"""Plan 48.4: Save to… an output into a folder of the chat's environment (Edit or above), numbered when the name is
taken, refused outside the environment, and undone like an edit."""

from __future__ import annotations

import pytest

import saving


@pytest.fixture
def proj(client, repo):
    assert client.post("/v1/folders", json={"path": str(repo), "level": "edit"}).status_code == 200
    return repo


@pytest.fixture
def fake_hub(monkeypatch):
    async def fetch(hub, oid):
        if oid == "000000000000":
            from folders import Refused
            raise Refused("unknown_output", f"no output {oid}", "", 404)
        return b"\x89PNG fake", "fox.png"
    monkeypatch.setattr(saving, "fetch_output", fetch)


def test_saved_numbered_and_undone(client, proj, fake_hub):
    r = client.post("/v1/save-output", json={"output_id": "aaaaaaaaaaaa", "folder": "proj", "thread": "t9"})
    assert r.status_code == 200, r.text
    assert (proj / "fox.png").read_bytes() == b"\x89PNG fake" and r.json()["path"].endswith("/fox.png")
    r2 = client.post("/v1/save-output", json={"output_id": "aaaaaaaaaaaa", "folder": str(proj / "pkg"), "thread": "t9"})
    assert r2.status_code == 200 and (proj / "pkg" / "fox.png").exists()
    r3 = client.post("/v1/save-output", json={"output_id": "aaaaaaaaaaaa", "folder": "proj", "thread": "t9"})
    assert (proj / "fox-2.png").exists() and r3.json()["summary"] == "saved fox-2.png"
    undo = r3.json()["undo"].removeprefix("/api/s/workspace")
    assert client.post(undo).json()["status"] == "undone" and not (proj / "fox-2.png").exists()


def test_refused_outside_the_environment_and_below_edit(client, repo, tmp_path, fake_hub):
    r = client.post("/v1/save-output", json={"output_id": "aaaaaaaaaaaa", "folder": str(tmp_path), "thread": "t9"})
    assert r.status_code == 403 and r.json()["code"] == "folder_not_allowed" and "Edit" in r.json()["fix"]
    assert client.post("/v1/folders", json={"path": str(repo), "level": "read"}).status_code == 200
    r = client.post("/v1/save-output", json={"output_id": "aaaaaaaaaaaa", "folder": "proj", "thread": "t9"})
    assert r.status_code == 403 and not (repo / "fox.png").exists()
    assert client.post("/v1/save-output", json={"output_id": "000000000000", "folder": "proj"}).status_code == 404


def test_names_are_cleaned_and_freed(tmp_path):
    assert saving.clean_name("../a/b.png") == "-a-b.png" and saving.clean_name("") == "output"
    (tmp_path / "x.png").write_text("1")
    assert saving.free_name(tmp_path, "x.png") == "x-2.png" and saving.free_name(tmp_path, "y.png") == "y.png"
