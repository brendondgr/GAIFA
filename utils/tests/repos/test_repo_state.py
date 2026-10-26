"""Each submodule's state and problems (plan mod-repos 3.1), on throwaway repositories with a bare
"GitHub": every problem code, a clean detached checkout, a fetch that can't reach the remote."""

from __future__ import annotations

import json

import pytest

from utils.repos import fetch, list_states, repo_state, submodules
from utils.tests.repos.gitfix import ENV, adopted, commit, g, upstream_commit


@pytest.fixture(autouse=True)
def _ident(monkeypatch):
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)


@pytest.fixture
def gaifa(tmp_path):
    return adopted(tmp_path)


def codes(st):
    return sorted(p.code for p in st.problems)


def test_submodules_from_gitmodules(gaifa, tmp_path):
    root, _, bare = gaifa
    assert submodules(root) == [("m", "services/m", str(bare), "main")]
    assert submodules(tmp_path) == []                      # no .gitmodules: none


def test_clean(gaifa):
    root, mod, _ = gaifa
    st = repo_state(root, "m")
    assert st.initialized and st.head == st.pinned and st.checkout_vs_pin == "same"
    assert st.pinned_on_remote is True and st.problems == [] and st.level is None


def test_detached_at_the_pin_is_fine(gaifa):
    root, mod, _ = gaifa
    g(mod, "checkout", "-q", "--detach")
    st = repo_state(root, "m")
    assert st.on_branch is None and st.problems == []


def test_dirty_and_untracked(gaifa):
    root, mod, _ = gaifa
    (mod / "service.toml").write_text('id = "m"\n# edited\n')
    (mod / "notes.txt").write_text("new")
    st = repo_state(root, "m")
    assert (st.dirty, st.untracked) == (1, 1) and codes(st) == ["dirty", "untracked"] and st.level == "warn"


def test_unpushed_and_ahead_of_pin(gaifa):
    root, mod, _ = gaifa
    commit(mod, "local only", {"x.py": "x"})
    st = repo_state(root, "m")
    assert st.unpushed == 1 and st.ahead == 1 and st.checkout_vs_pin == "ahead"
    assert codes(st) == ["checkout_ahead_of_pin", "unpushed"]
    assert next(p for p in st.problems if p.code == "unpushed").fix == "git -C services/m push"


def test_pin_not_on_remote(gaifa):
    root, mod, _ = gaifa
    commit(mod, "local only", {"x.py": "x"})
    g(root, "add", "services/m")
    g(root, "commit", "-qm", "pin an unpushed commit")
    st = repo_state(root, "m")
    assert st.pinned_on_remote is False and "pin_not_on_remote" in codes(st)


def test_updates_available_after_a_fetch(gaifa, tmp_path):
    root, _, bare = gaifa
    upstream_commit(tmp_path, bare, "u1")
    upstream_commit(tmp_path, bare, "u2")
    assert repo_state(root, "m").behind == 0               # nothing fetched yet
    assert fetch(root, "m") is None
    st = repo_state(root, "m")
    assert st.behind == 2 and codes(st) == ["updates_available"] and st.level == "info"
    assert st.last_fetch_ts and st.fetch_error is None


def test_checkout_behind_the_pin(gaifa, tmp_path):
    root, mod, bare = gaifa
    old = g(mod, "rev-parse", "HEAD")
    upstream_commit(tmp_path, bare, "u1")
    fetch(root, "m")
    g(mod, "checkout", "-q", "origin/main")
    g(root, "add", "services/m")
    g(root, "commit", "-qm", "pin u1")
    g(mod, "checkout", "-q", old)                          # as after a GAIFA pull without `submodule update`
    st = repo_state(root, "m")
    assert st.checkout_vs_pin == "behind" and "checkout_behind_pin" in codes(st)


def test_a_pin_this_checkout_has_never_fetched(gaifa, tmp_path):
    root, mod, bare = gaifa
    sha = upstream_commit(tmp_path, bare, "u1")
    g(root, "update-index", "--cacheinfo", f"160000,{sha},services/m")
    g(root, "commit", "-qm", "pin u1 from elsewhere")
    st = repo_state(root, "m")
    assert st.checkout_vs_pin == "behind" and st.pinned_on_remote is None


def test_diverged(gaifa, tmp_path):
    root, mod, bare = gaifa
    upstream_commit(tmp_path, bare, "u1")
    fetch(root, "m")
    g(mod, "checkout", "-q", "origin/main")
    g(root, "add", "services/m")
    g(root, "commit", "-qm", "pin u1")
    g(mod, "checkout", "-q", "-B", "side", "HEAD~1")
    commit(mod, "side work", {"s.py": "s"})
    st = repo_state(root, "m")
    assert st.checkout_vs_pin == "diverged" and "diverged" in codes(st) and st.level == "error"


def test_fetch_that_cant_reach_the_remote(gaifa, tmp_path):
    root, mod, _ = gaifa
    g(mod, "remote", "set-url", "origin", str(tmp_path / "gone.git"))
    error = fetch(root, "m")
    assert error and "gone.git" in error
    st = repo_state(root, "m")
    assert "fetch_failed" in codes(st) and "wrong_remote" in codes(st)
    log = json.loads((root / "data/state/repos/fetch.json").read_text())
    assert log["m"]["error"] == error


def test_a_renamed_branch(gaifa):
    root, *_ = gaifa
    g(root, "config", "-f", ".gitmodules", "submodule.services/m.branch", "trunk")
    error = fetch(root, "m")
    assert error and "trunk" in error


def test_not_checked_out(gaifa):
    root, mod, _ = gaifa
    g(root, "submodule", "deinit", "-q", "-f", "services/m")
    st = repo_state(root, "m")
    assert not st.initialized and codes(st) == ["not_checked_out"] and st.level == "error"
    assert "git submodule update --init services/m" in st.problems[0].fix
    assert fetch(root, "m") == "not checked out"


def test_list_states_and_dict(gaifa):
    root, *_ = gaifa
    [st] = list_states(root)
    d = st.to_dict()
    assert d["id"] == "m" and d["level"] is None and d["problems"] == []
