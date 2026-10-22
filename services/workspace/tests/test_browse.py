"""Plan 42.4: browsing folders to add one to an environment: inside the home folder and mounted drives only, without
hidden or secret-looking folders, each saying whether it can be added."""

from __future__ import annotations

import pytest

import folders as folders_mod


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(folders_mod, "grant_roots", lambda: [tmp_path])
    for d in ("Projects/app", "Projects/site", "Docs", ".ssh", "secrets", "node_modules"):
        (tmp_path / d).mkdir(parents=True)
    (tmp_path / "notes.txt").write_text("x")
    return tmp_path


def test_browse_lists_folders_only_and_hides_hidden_and_secret_ones(client, home):
    r = client.get("/v1/browse", params={"path": str(home)})
    assert r.status_code == 200, r.text
    body = r.json()
    names = [d["name"] for d in body["dirs"]]
    assert {"Docs", "node_modules", "Projects"} <= set(names)
    assert not {".ssh", "secrets", "notes.txt"} & set(names)                                  # no hidden or secret folders, no files
    assert names == sorted(names, key=str.lower)
    assert body["parent"] is None and body["path"] == str(home)                               # a root: no way up
    inner = client.get("/v1/browse", params={"path": str(home / "Projects")}).json()
    assert [d["name"] for d in inner["dirs"]] == ["app", "site"] and inner["parent"] == str(home) and inner["addable"]
    assert inner["roots"] == [{"name": str(home), "path": str(home)}]


def test_browse_refuses_outside_hidden_and_missing(client, home, tmp_path_factory):
    outside = tmp_path_factory.mktemp("elsewhere")
    assert client.get("/v1/browse", params={"path": str(outside)}).json()["code"] == "not_browsable"
    assert client.get("/v1/browse", params={"path": str(home / ".ssh")}).json()["code"] == "not_browsable"
    assert client.get("/v1/browse", params={"path": str(home / "nope")}).json()["code"] == "not_a_folder"
    assert client.get("/v1/browse", params={"path": "relative/path"}).json()["code"] == "bad_path"
