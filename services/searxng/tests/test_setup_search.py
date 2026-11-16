"""capability-enablement 5.3: scripts/setup_search.py, the searxng setup's steps: the stdlib probe (yours, yours_no_json,
none), `is` for ask_if, can-manage without a runtime, use-yours saving the choice."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
from conftest import SETTINGS

spec = importlib.util.spec_from_file_location("setup_search", Path(__file__).resolve().parents[1] / "scripts" / "setup_search.py")
ss = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ss)


@pytest.fixture(autouse=True)
def _own_root(tmp_path, monkeypatch):
    monkeypatch.setenv("GAIFA_ROOT", str(tmp_path))     # never this machine's own choice (data/state/searxng/source.json)


def test_probe_and_is(fake, folder, monkeypatch, capsys):
    monkeypatch.setattr(ss, "PROBES", ())
    monkeypatch.setenv("SEARXNG_URL", fake.url)
    assert ss.probe() == {"answer": "yours", "url": fake.url}
    assert ss.main(["x", "is", "yours"]) == 0 and ss.main(["x", "is", "none"]) == 1
    assert "the SearXNG here is yours" in capsys.readouterr().out
    (folder / "settings.yml").write_text(SETTINGS.replace("    - json\n", ""))
    fake.reload()
    assert ss.probe()["answer"] == "yours_no_json"
    monkeypatch.setenv("SEARXNG_URL", "http://127.0.0.1:9")
    assert ss.probe() == {"answer": "none", "url": None}


def test_can_manage(monkeypatch, capsys):
    monkeypatch.setattr(ss, "PROBES", ())
    monkeypatch.setenv("SEARXNG_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("GAIFA_CONTAINER_RUNTIME", "podman")
    assert ss.main(["x", "can-manage"]) == 0
    monkeypatch.setenv("GAIFA_CONTAINER_RUNTIME", "")
    monkeypatch.setattr(ss.shutil, "which", lambda c: None)
    assert ss.main(["x", "can-manage"]) == 1 and "install podman" in capsys.readouterr().out


def test_use_yours_saves_the_choice(fake, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(ss, "PROBES", ())
    monkeypatch.setenv("SEARXNG_URL", fake.url)
    monkeypatch.setenv("GAIFA_ROOT", str(tmp_path))
    assert ss.main(["x", "use-yours"]) == 0
    assert json.loads((tmp_path / "data/state/searxng/source.json").read_text()) == {"source": "yours", "url": fake.url}
    assert f"Using your SearXNG at {fake.url}" in capsys.readouterr().out


def test_gaifas_own_chosen_before_is_kept(fake, monkeypatch, tmp_path, capsys):
    """The fresh-clone check: once GAIFA's own is chosen, a later setup doesn't call the SearXNG it finds "yours" or
    switch back to it; the managed step runs to make sure it exists."""
    import source as src
    monkeypatch.setattr(ss, "PROBES", ())
    monkeypatch.setenv("SEARXNG_URL", fake.url)
    monkeypatch.setenv("GAIFA_CONTAINER_RUNTIME", "podman")
    src.save("managed", "http://127.0.0.1:5200")
    assert ss.main(["x", "is", "yours"]) == 1 and "GAIFA's own SearXNG is the one search uses" in capsys.readouterr().out
    assert ss.main(["x", "use-yours"]) == 0 and src.load()["source"] == "managed"
    assert ss.main(["x", "can-manage"]) == 0
