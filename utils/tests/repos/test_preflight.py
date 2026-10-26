"""The preflight report and the push (plan mod-repos 1.2–1.3), against a bare "GitHub"."""

from __future__ import annotations

import pytest

from utils.repos import GitError
from utils.repos_migrate import preflight, push, report
from utils.tests.repos.gitfix import commit, g, mod_repo, project, subtree_add


@pytest.fixture
def setup(tmp_path):
    work, bare = mod_repo(tmp_path)
    root = project(tmp_path)
    subtree_add(root, "m", work)
    return root, work, bare


def test_clean_fast_forward(setup):
    root, _, bare = setup
    commit(root, "GAIFA (1): status", {"services/m/status.py": "s\n"})
    pf = preflight(root, "m", str(bare), "main")
    assert pf.ok and pf.fast_forward and not pf.secrets and not pf.large
    assert [c.split(" ", 2)[2] for c in pf.commits] == ["GAIFA (1): status"]
    assert "| `m` |" in report([pf]) and "Secrets:** none found" in report([pf])


def test_unpushed_commits_of_the_old_clone_are_included(tmp_path):
    work, bare = mod_repo(tmp_path)
    commit(work, "never pushed", {"app.py": "v2b\n"})   # like LLMs' 4 and LocalTTS' 1
    root = project(tmp_path)
    subtree_add(root, "m", work)
    commit(root, "GAIFA (1)", {"services/m/a.py": "a\n"})
    pf = preflight(root, "m", str(bare), "main")
    assert pf.fast_forward
    assert [c.split(" ", 2)[2] for c in pf.commits] == ["GAIFA (1)", "never pushed"]


def test_diverged_remote(setup):
    root, work, bare = setup
    commit(work, "pushed after the move", {"other.py": "o\n"})
    g(work, "push", "-q", "origin", "main")
    commit(root, "GAIFA (1)", {"services/m/a.py": "a\n"})
    pf = preflight(root, "m", str(bare), "main")
    assert not pf.fast_forward and not pf.ok
    assert "Not a fast-forward" in report([pf])


def test_planted_key_and_home_path(setup):
    root, _, bare = setup
    key = "sk-ant-" + "A1b2C3d4" * 4
    commit(root, "GAIFA (1): oops", {"services/m/conf.py": f'KEY = "{key}"\nPATH = "/home/someone/models"\n',
                                     "services/m/.env.example": "OPENAI_API_KEY=abcdefghijklmnop1234\n"})
    pf = preflight(root, "m", str(bare), "main")
    assert not pf.ok
    kinds = sorted({f.kind for f in pf.secrets})
    assert kinds == ["API key (sk-…)", "secret assignment"]
    assert all(key not in f.text for f in pf.secrets)       # masked in the report
    assert pf.home_paths == {"conf.py": 1}            # paths inside the mod
    assert key not in report([pf])


def test_large_file(setup, monkeypatch):
    root, _, bare = setup
    monkeypatch.setattr("utils.repos_migrate.LARGE_BYTES", 10)
    commit(root, "GAIFA (1): big", {"services/m/weights.bin": "x" * 100})
    pf = preflight(root, "m", str(bare), "main")
    assert pf.large == [("weights.bin", 100)] and not pf.ok


def test_unreachable_remote(setup, tmp_path):
    root, *_ = setup
    pf = preflight(root, "m", str(tmp_path / "missing.git"), "main")
    assert pf.error and not pf.ok


def test_push_fast_forwards_and_confirms(setup):
    root, _, bare = setup
    commit(root, "GAIFA (1)", {"services/m/a.py": "a\n"})
    pf = preflight(root, "m", str(bare), "main")
    assert push(root, "m", str(bare), "main") == pf.head
    assert g(bare, "rev-parse", "main") == pf.head


def test_push_never_forces(setup):
    root, work, bare = setup
    commit(work, "pushed after the move", {"other.py": "o\n"})
    g(work, "push", "-q", "origin", "main")
    commit(root, "GAIFA (1)", {"services/m/a.py": "a\n"})
    preflight(root, "m", str(bare), "main")
    with pytest.raises(GitError):
        push(root, "m", str(bare), "main")
    assert g(bare, "log", "-1", "--format=%s", "main") == "pushed after the move"
