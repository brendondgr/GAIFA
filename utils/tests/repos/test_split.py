"""`split` (plan mod-repos 1.2): a mod folder's GAIFA history as commits on top of its own repository."""

from __future__ import annotations

import pytest

from utils.repos import GitError
from utils.repos_split import split
from utils.tests.repos.gitfix import commit, g, mod_repo, project, subtree_add


@pytest.fixture
def setup(tmp_path):
    work, bare = mod_repo(tmp_path)
    root = project(tmp_path)
    add = subtree_add(root, "m", work)
    return root, work, bare, add


def test_split_replays_the_mods_commits_on_its_history(setup):
    root, work, _, _ = setup
    commit(root, "GAIFA (1): status route", {"services/m/status.py": "s\n", "utils/x.py": "hub\n"})
    commit(root, "GAIFA (2): the hub only", {"utils/y.py": "hub\n"})
    commit(root, "GAIFA (3): app v3", {"services/m/app.py": "v3\n"})
    s = split(root, "m")
    assert s.base == g(work, "rev-parse", "HEAD")
    assert s.commits == 2
    assert g(root, "log", "--format=%s", f"{s.base}..{s.head}").splitlines() == ["GAIFA (3): app v3", "GAIFA (1): status route"]
    assert g(root, "rev-parse", f"{s.head}^{{tree}}") == g(root, "rev-parse", "HEAD:services/m")
    assert g(root, "rev-parse", "refs/heads/split/m") == s.head
    # each commit carries only the folder, at that point
    assert g(root, "ls-tree", "--name-only", f"{s.head}~1").splitlines() == [".gitignore", "app.py", "status.py"]
    assert g(root, "show", f"{s.head}~1:app.py") == "v2"


def test_split_keeps_authors_dates_and_messages(setup):
    root, *_ = setup
    commit(root, "GAIFA (1): line one\n\nA body with détails.", {"services/m/a.py": "a\n"})
    s = split(root, "m")
    src = g(root, "log", "-1", "--format=%an|%ae|%ad|%cd|%B", "HEAD")
    assert g(root, "log", "-1", "--format=%an|%ae|%ad|%cd|%B", s.head) == src


def test_split_is_deterministic(setup):
    root, *_ = setup
    commit(root, "GAIFA (1)", {"services/m/a.py": "a\n"})
    assert split(root, "m", ref=False).head == split(root, "m", ref=False).head


def test_split_is_a_fast_forward_of_the_remote(setup):
    root, _, bare, _ = setup
    commit(root, "GAIFA (1)", {"services/m/a.py": "a\n"})
    s = split(root, "m")
    remote = g(bare, "rev-parse", "main")
    assert g(root, "merge-base", s.head, remote) == remote


def test_split_through_a_merge(setup):
    root, *_ = setup
    g(root, "checkout", "-q", "-b", "side")
    commit(root, "side: b", {"services/m/b.py": "b\n"})
    g(root, "checkout", "-q", "main")
    commit(root, "main: c", {"services/m/c.py": "c\n"})
    g(root, "merge", "-q", "--no-edit", "side")
    s = split(root, "m")
    assert g(root, "rev-parse", f"{s.head}^{{tree}}") == g(root, "rev-parse", "HEAD:services/m")
    assert len(g(root, "rev-list", "--parents", "-n1", s.head).split()) == 3   # the merge is kept


def test_merge_of_a_branch_that_never_touched_the_mod(setup):
    root, *_ = setup
    g(root, "checkout", "-q", "-b", "docs")
    commit(root, "docs only", {"docs/a.md": "a\n"})
    g(root, "checkout", "-q", "main")
    commit(root, "main: c", {"services/m/c.py": "c\n"})
    g(root, "merge", "-q", "--no-edit", "docs")
    s = split(root, "m")
    assert s.commits == 1
    assert g(root, "log", "--format=%s", "-1", s.head) == "main: c"


def test_no_changes_since_the_add(setup):
    root, work, *_ = setup
    commit(root, "hub only", {"utils/z.py": "z\n"})
    s = split(root, "m")
    assert s.head == g(work, "rev-parse", "HEAD") and s.commits == 0


def test_no_subtree_add(tmp_path):
    root = project(tmp_path)
    with pytest.raises(GitError, match="no \"Add 'services/m/'"):
        split(root, "m")
