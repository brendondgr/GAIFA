import os

import pytest

from utils.paths import Paths, project_root, write_atomic


def test_root_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("GAIFA_ROOT", str(tmp_path))
    assert project_root() == tmp_path.resolve()


def test_root_defaults_to_app_folder(monkeypatch):
    monkeypatch.delenv("GAIFA_ROOT", raising=False)
    assert (project_root() / "pyproject.toml").exists()


def test_build_and_ensure(tmp_path):
    p = Paths.build(tmp_path)
    assert not p.models.exists()
    p.ensure()
    assert p.models.is_dir() and p.databases.is_dir() and p.outputs.is_dir()
    assert p.hub_db == tmp_path / "data/databases/hub.db"
    assert p.rel(p.outputs / "tts") == "outputs/tts"


def test_paths_must_stay_inside_root(tmp_path):
    with pytest.raises(ValueError, match="paths.outputs"):
        Paths.build(tmp_path, outputs="../elsewhere")


def test_write_atomic_replaces_and_keeps_mode(tmp_path):
    f = tmp_path / "a" / "x.json"
    write_atomic(f, "one")
    assert f.read_text() == "one"
    assert f.stat().st_mode & 0o777 == 0o644
    os.chmod(f, 0o600)
    write_atomic(f, b"two")
    assert f.read_text() == "two"
    assert f.stat().st_mode & 0o777 == 0o600
    assert [x.name for x in f.parent.iterdir()] == ["x.json"]


def test_write_atomic_failure_leaves_original(tmp_path):
    f = tmp_path / "x.txt"
    write_atomic(f, "keep")
    with pytest.raises(TypeError):
        write_atomic(f, 123)  # type: ignore[arg-type]
    assert f.read_text() == "keep"
    assert [x.name for x in tmp_path.iterdir()] == ["x.txt"]
