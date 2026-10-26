"""`adopt` (plan mod-repos 2.1): a mod folder becomes a submodule in place, its files untouched."""

from __future__ import annotations

import pytest

from utils.repos import GitError
from utils.repos_adopt import adopt, diff_snapshots, snapshot
from utils.repos_migrate import preflight, push
from utils.tests.repos.gitfix import ENV, commit, g, mod_repo, project, subtree_add

MSG = "GAIFA (mod-repos 2.2): m is a submodule\n"


@pytest.fixture(autouse=True)
def _ident(monkeypatch):
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)


@pytest.fixture
def setup(tmp_path):
    work, bare = mod_repo(tmp_path)
    root = project(tmp_path)
    subtree_add(root, "m", work)
    commit(root, "GAIFA (1): status", {"services/m/status.py": "s\n", "services/m/.gitignore": ".venv/\nruntime/\n.env\n"})
    preflight(root, "m", str(bare), "main")
    push(root, "m", str(bare), "main")
    mod = root / "services" / "m"
    (mod / ".venv" / "bin").mkdir(parents=True)
    (mod / ".venv" / "bin" / "python").write_text("py")
    (mod / "runtime").mkdir()
    (mod / "runtime" / "engine.bin").write_text("weights")
    (mod / ".env").write_text("KEY=secret\n")
    return root, bare, mod


def test_adopt_in_place(setup, tmp_path):
    root, bare, mod = setup
    before = snapshot(mod)
    gaifa_head = g(root, "rev-parse", "HEAD")
    new = adopt(root, "m", str(bare), "main", MSG, state_dir=tmp_path / "state")
    assert diff_snapshots(before, snapshot(mod)) == []
    assert (mod / ".git").is_file()                                   # absorbed into GAIFA's .git/modules
    assert g(root, "rev-parse", "HEAD") == new and g(root, "rev-parse", "HEAD~1") == gaifa_head
    assert g(root, "ls-tree", "HEAD", "services/m").split()[:3] == ["160000", "commit", g(bare, "rev-parse", "main")]
    assert 'path = services/m' in g(root, "show", "HEAD:.gitmodules") and "branch = main" in g(root, "show", "HEAD:.gitmodules")
    assert g(root, "status", "--porcelain") == ""                     # the shared index follows HEAD
    assert g(mod, "status", "--porcelain") == ""
    assert g(mod, "rev-parse", "--abbrev-ref", "@{u}") == "origin/main"
    assert g(root, "submodule", "status").split()[1] == "services/m"
    assert (mod / ".env").read_text() == "KEY=secret\n"


def test_adopt_keeps_others_staged_and_unstaged_work(setup, tmp_path):
    root, bare, _ = setup
    (root / "app.py").write_text("someone else's change\n")
    (root / "notes.md").write_text("staged by another session\n")
    g(root, "add", "notes.md")
    adopt(root, "m", str(bare), "main", MSG, state_dir=tmp_path / "state")
    assert g(root, "status", "--porcelain").splitlines() == ["M app.py", "A  notes.md"]   # g() strips the leading space
    assert "notes.md" not in g(root, "show", "--stat", "--format=", "HEAD")


def test_refuses_uncommitted_changes(setup, tmp_path):
    root, bare, mod = setup
    (mod / "status.py").write_text("edited\n")
    with pytest.raises(GitError, match="hasn't committed"):
        adopt(root, "m", str(bare), "main", MSG, state_dir=tmp_path / "state")
    assert not (mod / ".git").exists()


def test_refuses_a_remote_that_differs(setup, tmp_path):
    root, bare, mod = setup
    commit(root, "GAIFA (2): not pushed", {"services/m/later.py": "l\n"})
    with pytest.raises(GitError, match="doesn't hold what GAIFA has"):
        adopt(root, "m", str(bare), "main", MSG, state_dir=tmp_path / "state")
    assert not (mod / ".git").exists()                                # rolled back
    assert g(root, "status", "--porcelain") == ""


def test_refuses_a_missing_ignore_rule(setup, tmp_path):
    root, bare, mod = setup
    (mod / "cache.tmp").write_text("x")
    (root / ".gitignore").write_text("/services/*/.venv/\n*.tmp\n")
    commit(root, "root ignores *.tmp", {})
    with pytest.raises(GitError, match="isn't clean as its own repository"):
        adopt(root, "m", str(bare), "main", MSG, state_dir=tmp_path / "state")
    assert not (mod / ".git").exists()


def test_refuses_twice(setup, tmp_path):
    root, bare, _ = setup
    adopt(root, "m", str(bare), "main", MSG, state_dir=tmp_path / "state")
    with pytest.raises(GitError, match="already a repository"):
        adopt(root, "m", str(bare), "main", MSG, state_dir=tmp_path / "state")


def test_second_mod_appends_to_gitmodules(tmp_path):
    w1, b1 = mod_repo(tmp_path, "a")
    w2, b2 = mod_repo(tmp_path, "b")
    root = project(tmp_path)
    subtree_add(root, "a", w1)
    subtree_add(root, "b", w2)
    adopt(root, "a", str(b1), "main", MSG, state_dir=tmp_path / "state")
    adopt(root, "b", str(b2), "main", MSG, state_dir=tmp_path / "state")
    mods = g(root, "show", "HEAD:.gitmodules")
    assert '[submodule "services/a"]' in mods and '[submodule "services/b"]' in mods
    assert len(g(root, "submodule", "status").splitlines()) == 2


def test_files_a_running_mod_writes_are_listed_not_fatal(setup, tmp_path, monkeypatch):
    root, bare, mod = setup
    import utils.repos_adopt as ra
    real = ra.snapshot
    calls = []

    def snap(folder):
        calls.append(1)
        if len(calls) == 2:                                           # the mod logs during the adoption
            (folder / "runtime" / "log.txt").write_text("line\n")
        return real(folder)
    monkeypatch.setattr(ra, "snapshot", snap)
    adopt(root, "m", str(bare), "main", MSG, state_dir=tmp_path / "state")
    assert (tmp_path / "state" / "adopt-m-diff.txt").read_text() == "new: runtime/log.txt\n"


def test_a_lost_file_is_an_error(setup, tmp_path, monkeypatch):
    root, bare, mod = setup
    import utils.repos_adopt as ra
    real = ra.snapshot
    calls = []

    def snap(folder):
        calls.append(1)
        if len(calls) == 2:
            (folder / ".env").unlink()
        return real(folder)
    monkeypatch.setattr(ra, "snapshot", snap)
    with pytest.raises(GitError, match="lost files"):
        adopt(root, "m", str(bare), "main", MSG, state_dir=tmp_path / "state")
