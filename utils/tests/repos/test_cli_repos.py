"""`gaifa repos` (plan mod-repos 3.2): update with install, restart, check and rollback; pin; sync;
the refusals and the lock; the status lines and exit codes. Throwaway repositories, fake hooks."""

from __future__ import annotations

import argparse
import json
import os
import types

import pytest

from utils import cli_repos
from utils.repos import repo_state
from utils.repos_update import Hooks, pin, sync, update
from utils.tests.repos.gitfix import ENV, adopted, commit, g, upstream_commit


@pytest.fixture(autouse=True)
def _ident(monkeypatch):
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)


@pytest.fixture
def gaifa(tmp_path):
    return adopted(tmp_path)


class Calls(list):
    def hooks(self, check=(True, "all checks passed"), install_rc=0, running=True, busy=None, tests=(True, "1 passed")):
        def install(sid):
            self.append(("install", sid))
            return install_rc
        return Hooks(install=install, running=lambda sid: running, restart=lambda sid: self.append(("restart", sid)),
                     check=lambda sid: (self.append(("check", sid)), check)[1], busy=lambda sid: busy,
                     tests=lambda: (self.append(("tests",)), tests)[1])


def pinned(root):
    return g(root, "ls-files", "-s", "services/m").split()[1]


def test_update_fast_forwards_restarts_checks_and_stages(gaifa, tmp_path):
    root, mod, bare = gaifa
    old = g(mod, "rev-parse", "HEAD")
    new = upstream_commit(tmp_path, bare, "u1")
    calls = Calls()
    r = update(root, "m", hooks=calls.hooks())
    assert r.ok and r.old == old and r.new == new and r.staged and not r.rolled_back
    assert [c.split(" ", 1)[1] for c in r.commits] == ["u1"]
    assert calls == [("restart", "m"), ("check", "m")]                       # no dependency changed: no install
    assert g(mod, "rev-parse", "HEAD") == new and g(mod, "symbolic-ref", "--short", "HEAD") == "main"
    assert pinned(root) == new and g(root, "ls-tree", "HEAD", "services/m").split()[2] == old   # staged, not committed


def test_a_dependency_change_runs_the_install(gaifa, tmp_path):
    root, _, bare = gaifa
    upstream_commit(tmp_path, bare, "deps", {"requirements.txt": "httpx\n"})
    calls = Calls()
    r = update(root, "m", hooks=calls.hooks(running=False))
    assert r.ok and r.installed and calls == [("install", "m"), ("check", "m")]


def test_a_failed_check_rolls_back(gaifa, tmp_path):
    root, mod, bare = gaifa
    old = g(mod, "rev-parse", "HEAD")
    upstream_commit(tmp_path, bare, "breaks", {"requirements.txt": "nope\n"})
    calls = Calls()
    r = update(root, "m", hooks=calls.hooks(check=(False, "health: refused")))
    assert not r.ok and r.rolled_back and "gaifa check failed: health: refused" in r.message
    assert calls == [("install", "m"), ("restart", "m"), ("check", "m"), ("install", "m"), ("restart", "m")]
    assert g(mod, "rev-parse", "HEAD") == old and pinned(root) == old
    assert repo_state(root, "m").problems[0].code == "updates_available"     # still offered


def test_a_failed_install_rolls_back(gaifa, tmp_path):
    root, mod, bare = gaifa
    old = g(mod, "rev-parse", "HEAD")
    upstream_commit(tmp_path, bare, "deps", {"uv.lock": "x\n"})
    r = update(root, "m", hooks=Calls().hooks(install_rc=2))
    assert r.rolled_back and "the install exited 2" in r.message and g(mod, "rev-parse", "HEAD") == old


def test_hub_down_moves_but_says_unchecked(gaifa, tmp_path):
    root, _, bare = gaifa
    upstream_commit(tmp_path, bare, "u1")
    r = update(root, "m", hooks=Hooks(check=lambda sid: (None, "the hub isn't running")))
    assert r.ok and r.checked is None and "not checked: the hub isn't running" in r.message


def test_dry_run_changes_nothing(gaifa, tmp_path):
    root, mod, bare = gaifa
    old = g(mod, "rev-parse", "HEAD")
    upstream_commit(tmp_path, bare, "u1")
    r = update(root, "m", dry_run=True, hooks=Calls().hooks())
    assert r.ok and len(r.commits) == 1 and "would move" in r.message
    assert g(mod, "rev-parse", "HEAD") == old and pinned(root) == old


def test_up_to_date(gaifa):
    root, *_ = gaifa
    r = update(root, "m", hooks=Calls().hooks())
    assert r.ok and "up to date" in r.message and not r.staged


@pytest.mark.parametrize("make, code", [
    (lambda mod: (mod / "service.toml").write_text("changed\n"), "dirty"),
    (lambda mod: commit(mod, "local only", {"x.py": "x"}), "unpushed"),
])
def test_refusals(gaifa, tmp_path, make, code):
    root, mod, bare = gaifa
    upstream_commit(tmp_path, bare, "u1")
    make(mod)
    head = g(mod, "rev-parse", "HEAD")
    calls = Calls()
    r = update(root, "m", hooks=calls.hooks())
    assert not r.ok and code in r.refused and calls == []
    assert g(mod, "rev-parse", "HEAD") == head                                # nothing moved


def test_refuses_a_busy_mod_unless_forced(gaifa, tmp_path):
    root, _, bare = gaifa
    upstream_commit(tmp_path, bare, "u1")
    r = update(root, "m", hooks=Calls().hooks(busy="1 job(s): a mesh"))
    assert r.refused == ["busy"] and "a mesh" in r.message
    assert update(root, "m", force_busy=True, hooks=Calls().hooks(busy="1 job(s)")).ok


def test_refuses_a_rewritten_branch(gaifa, tmp_path):
    root, mod, bare = gaifa
    other = tmp_path / "rw"
    g(tmp_path, "clone", "-q", str(bare), str(other))
    g(other, "reset", "-q", "--hard", "HEAD~1")
    commit(other, "rewritten", {"r.py": "r"})
    g(other, "push", "-q", "-f", "origin", "main")
    r = update(root, "m", hooks=Calls().hooks())
    assert not r.ok and "diverged" in r.refused


def test_not_checked_out(gaifa):
    root, *_ = gaifa
    g(root, "submodule", "deinit", "-q", "-f", "services/m")
    r = update(root, "m", hooks=Calls().hooks())
    assert r.refused == ["not_checked_out"]


def test_one_update_at_a_time(gaifa):
    root, *_ = gaifa
    lock = root / "data/state/repos/update.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(json.dumps({"pid": os.getpid(), "ts": 9e12}))          # held by a live process, fresh
    r = update(root, "m", hooks=Calls().hooks())
    assert r.refused == ["locked"]
    lock.write_text(json.dumps({"pid": 999_999_999, "ts": 0}))              # its process is gone
    assert update(root, "m", hooks=Calls().hooks()).ok and not lock.exists()


def test_to_a_given_commit(gaifa, tmp_path):
    root, mod, bare = gaifa
    first = upstream_commit(tmp_path, bare, "u1")
    upstream_commit(tmp_path, bare, "u2")
    r = update(root, "m", to=first, hooks=Calls().hooks())
    assert r.ok and r.new == first and g(mod, "rev-parse", "HEAD") == first


def test_commit_runs_the_tests_and_commits_only_the_pin(gaifa, tmp_path):
    root, mod, bare = gaifa
    new = upstream_commit(tmp_path, bare, "u1")
    (root / "notes.md").write_text("another session's work\n")
    g(root, "add", "notes.md")
    calls = Calls()
    r = update(root, "m", commit=True, hooks=calls.hooks())
    assert r.ok and r.committed and ("tests",) in calls
    assert g(root, "ls-tree", "HEAD", "services/m").split()[2] == new
    assert g(root, "show", "--name-only", "--format=", "HEAD").split() == ["services/m"]
    assert "GAIFA (repos): m →" in g(root, "log", "-1", "--format=%s")
    assert g(root, "status", "--porcelain").splitlines() == ["A  notes.md"]   # theirs still staged, not committed


def test_commit_with_failing_tests_only_stages(gaifa, tmp_path):
    root, _, bare = gaifa
    new = upstream_commit(tmp_path, bare, "u1")
    head = g(root, "rev-parse", "HEAD")
    r = update(root, "m", commit=True, hooks=Calls().hooks(tests=(False, "1 failed")))
    assert r.ok and r.staged and not r.committed and "tests failed (1 failed)" in r.message
    assert g(root, "rev-parse", "HEAD") == head and pinned(root) == new


def test_pin(gaifa):
    root, mod, _ = gaifa
    commit(mod, "local", {"x.py": "x"})
    assert pin(root, "m").refused == ["unpushed"]
    g(mod, "push", "-q", "origin", "main")
    r = pin(root, "m")
    assert r.ok and r.staged and pinned(root) == g(mod, "rev-parse", "HEAD") and len(r.commits) == 1
    r = pin(root, "m", commit=True)
    assert r.committed and g(root, "ls-tree", "HEAD", "services/m").split()[2] == g(mod, "rev-parse", "HEAD")


def test_sync_after_a_pull_and_after_a_clone(gaifa, tmp_path, monkeypatch):
    root, mod, bare = gaifa
    old = g(mod, "rev-parse", "HEAD")
    new = upstream_commit(tmp_path, bare, "u1")
    g(root, "update-index", "--cacheinfo", f"160000,{new},services/m")
    g(root, "commit", "-qm", "pin u1")                                        # as a pull of GAIFA would bring
    assert repo_state(root, "m").checkout_vs_pin == "behind"
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")                               # local paths as submodule URLs (tests only)
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "protocol.file.allow")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "always")
    r = sync(root, "m")
    assert r.ok and g(mod, "rev-parse", "HEAD") == new != old
    g(root, "submodule", "deinit", "-q", "-f", "services/m")
    assert sync(root, "m").ok and repo_state(root, "m").checkout_vs_pin == "same"


def test_sync_refuses_changes(gaifa, tmp_path):
    root, mod, bare = gaifa
    new = upstream_commit(tmp_path, bare, "u1")
    g(root, "update-index", "--cacheinfo", f"160000,{new},services/m")
    g(root, "commit", "-qm", "pin u1")
    (mod / "service.toml").write_text("x\n")
    assert sync(root, "m").refused == ["dirty"]
    assert (mod / "service.toml").read_text() == "x\n"


def test_status_lines_and_exit_codes(gaifa, tmp_path, capsys, monkeypatch):
    root, mod, _ = gaifa
    monkeypatch.setattr(cli_repos, "cli", types.SimpleNamespace(ROOT=root))
    assert cli_repos.cmd_status(argparse.Namespace(json=False)) == 0
    assert "ok    m        pinned" in capsys.readouterr().out
    (mod / "service.toml").write_text("x\n")
    assert cli_repos.cmd_status(argparse.Namespace(json=False)) == 1
    out = capsys.readouterr().out
    assert "WARN  m" in out and "fix: commit them in services/m" in out
    assert cli_repos.cmd_status(argparse.Namespace(json=True)) == 1
    assert json.loads(capsys.readouterr().out)[0]["problems"][0]["code"] == "dirty"


def test_the_parser(monkeypatch):
    sub = argparse.ArgumentParser().add_subparsers(dest="cmd")
    cli_repos.add_parser(sub)
    p = sub.choices["repos"]
    a = p.parse_args(["update", "relay", "--dry-run", "--to", "abc"])
    assert (a.repos_cmd, a.id, a.dry_run, a.to, a.commit) == ("update", "relay", True, "abc", False)
    assert p.parse_args([]).repos_cmd is None
