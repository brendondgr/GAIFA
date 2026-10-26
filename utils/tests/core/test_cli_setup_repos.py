"""`gaifa setup` and the submodule mods (plan mod-repos 4.3): a clone without them, a checkout that
fails, which targets need which mod, and what the plan says about a mod it couldn't check out."""

from __future__ import annotations

from pathlib import Path

import pytest

from utils import cli_setup
from utils import cli_setup_repos as sr
from utils.tests.core.test_cli_setup import FakeProbe, FakeRunner, args, out, root  # noqa: F401 (root is a fixture)
from utils.tests.repos.gitfix import ENV, adopted, g


@pytest.fixture
def clone(tmp_path, monkeypatch):
    """A clone of a GAIFA-like project made without --recurse-submodules: services/mo is empty."""
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")                 # local paths as submodule URLs (tests only)
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "protocol.file.allow")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "always")
    src, _, _ = adopted(tmp_path, 'id = "mo"\n', sid="mo")
    dest = tmp_path / "clone"
    g(tmp_path, "clone", "-q", str(src), str(dest))
    return dest


def test_a_clone_without_submodules(clone):
    assert sr.submodules(clone)[0][:2] == ("mo", "services/mo")
    assert [s[0] for s in sr.missing(clone)] == ["mo"] and not any((clone / "services/mo").iterdir())
    r = sr.checkout(clone, ["mo"])
    assert r == {"done": ["mo"], "failed": []}
    assert (clone / "services/mo/service.toml").read_text() == 'id = "mo"\n' and sr.missing(clone) == []
    assert sr.checkout(clone, []) == {"done": [], "failed": []}                 # nothing left to check out


def test_only_the_targets_mods(clone):
    assert sr.checkout(clone, ["agent"]) == {"done": [], "failed": []}
    assert sr.missing(clone)                                                    # untouched


def test_a_checkout_that_fails(clone, tmp_path):
    g(clone, "config", "-f", ".gitmodules", "submodule.services/mo.url", str(tmp_path / "gone.git"))
    g(clone, "submodule", "sync", "-q")
    r = sr.checkout(clone, ["mo"])
    [f] = r["failed"]
    assert r["done"] == [] and f["setup"] == "mo" and f["mod"] == "mo" and "gone.git" in f["why"]
    assert f["fix"] and "(fix: " in f["why"]


@pytest.mark.parametrize("targets, sid, hit", [([], "tts", True), (["tts"], "tts", True), (["tts-kokoro"], "tts", True),
                                               (["agent"], "tts", False), (["ttsx"], "tts", False)])
def test_wanted(targets, sid, hit):
    assert sr.wanted(targets, sid) is hit


def test_fix_texts():
    assert "SSH key with access to git@github.com:brendondgr/LLMs.git" in sr._fix("git@github.com:brendondgr/LLMs.git", "Permission denied (publickey).")
    assert "network" in sr._fix("u", "ssh: Could not resolve hostname github.com")


def test_setup_leaves_out_a_mod_it_couldnt_check_out(root: Path, capsys, monkeypatch) -> None:  # noqa: F811
    fail = {"setup": "relay", "mod": "relay", "url": "git@github.com:brendondgr/Relay.git", "error": "Permission denied (publickey).",
            "fix": "add an SSH key", "why": "couldn't check out git@github.com:brendondgr/Relay.git: Permission denied (publickey). (fix: add an SSH key)"}
    seen = []
    monkeypatch.setattr(sr, "checkout", lambda r, t: (seen.append(list(t)), {"done": [], "failed": [fail]})[1])
    (root / "services" / "relay").rename(root / "relay-gone")                 # its docs are in the folder: not offered
    assert cli_setup.cmd_setup(args("tts", "relay", plan=True), FakeRunner(), FakeProbe()) == 0
    p = out(capsys)
    assert seen == [["tts", "relay"]] and p["setups"] == ["tts-kokoro"]
    assert {"setup": "relay", "why": fail["why"]}.items() <= p["unavailable"][-1].items()
    assert p["checkouts"]["failed"][0]["setup"] == "relay"
    assert cli_setup.cmd_setup(args("relay", plan=True), FakeRunner(), FakeProbe()) == 1   # nothing else: stopped
    s = out(capsys)
    assert s["stage"] == "stopped" and s["reason"] == "unavailable" and s["unavailable"][0]["why"] == fail["why"]


def test_setup_checks_out_before_it_reads_the_docs(root: Path, capsys, monkeypatch) -> None:  # noqa: F811
    moved = root / "relay-later"
    (root / "services" / "relay").rename(moved)

    def checkout(r, t):
        moved.rename(root / "services" / "relay")                              # what `git submodule update --init` does
        return {"done": ["relay"], "failed": []}
    monkeypatch.setattr(sr, "checkout", checkout)
    assert cli_setup.cmd_setup(args("relay", plan=True, json=False), FakeRunner(), FakeProbe()) == 0
    text = capsys.readouterr().out
    assert "Setup plan: relay" in text and "Checked out (their own repositories): relay" in text
