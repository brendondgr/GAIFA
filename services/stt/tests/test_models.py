"""Presets, the default model, and the device and precision each model runs at (plan 29.1)."""

from __future__ import annotations

import pytest

from stt import catalog


@pytest.mark.parametrize(("preset", "model"), [("fast", "base"), ("balanced", "small"),
                                               ("accurate", "large-v3-turbo"), ("best", "large-v3")])
def test_each_preset_names_its_model(preset, model):
    assert catalog.pick(preset=preset) == model


def test_the_default_is_balanced_which_is_small():
    assert catalog.pick() == "small"
    assert catalog.DEFAULT_PRESET == "balanced"


def test_a_model_by_name_wins_over_a_preset():
    assert catalog.pick(model="tiny", preset="best") == "tiny"
    assert catalog.pick(model="medium") == "medium"


def test_unknown_names_are_refused_with_the_choices():
    with pytest.raises(catalog.UnknownModel, match="balanced"):
        catalog.pick(preset="quick")
    with pytest.raises(catalog.UnknownModel, match="large-v3-turbo"):
        catalog.pick(model="huge")


@pytest.mark.parametrize("model", [m.name for m in catalog.CATALOG])
def test_float16_on_the_gpu_and_int8_on_the_cpu(model):
    assert catalog.compute_for(model, gpu=True) == ("cuda", "float16")
    assert catalog.compute_for(model, gpu=False) == ("cpu", "int8")


def test_int8_on_the_gpu_only_for_tiny_and_base():
    assert catalog.compute_for("tiny", gpu=True, precision="int8") == ("cuda", "int8")
    assert catalog.compute_for("base", gpu=True, precision="int8") == ("cuda", "int8")
    for model in ("small", "medium", "large-v3-turbo", "large-v3"):
        assert catalog.compute_for(model, gpu=True, precision="int8") == ("cuda", "float16")


def test_weights_are_copied_from_the_hf_cache_into_their_own_folder(tmp_path):
    snap = tmp_path / "hub" / "models--Systran--faster-whisper-base" / "snapshots" / "abc123"
    snap.mkdir(parents=True)
    blob = tmp_path / "blob"
    blob.write_bytes(b"weights")
    (snap / "model.bin").symlink_to(blob)
    (snap / "config.json").write_text("{}")
    weights = tmp_path / "models" / "stt"

    got = catalog.fetch(weights, "base", cache=tmp_path / "hub")

    assert got == {"source": "copied", "revision": "abc123"}
    assert catalog.is_downloaded(weights, "base")
    assert not (weights / "base" / "model.bin").is_symlink()          # a copy, not a link out of the root
    assert not (weights / "base.part").exists()
    assert catalog.fetch(weights, "base", cache=tmp_path / "hub")["source"] == "present"


def test_models_lists_size_download_and_how_it_runs(tmp_path):
    (tmp_path / "small").mkdir()
    (tmp_path / "small" / "model.bin").write_bytes(b"x")
    (tmp_path / "small" / "config.json").write_text("{}")
    rows = {r["name"]: r for r in catalog.describe(tmp_path, loaded="small", gpu=True)}
    assert rows["small"]["downloaded"] and rows["small"]["loaded"]
    assert rows["small"]["default"] and rows["small"]["preset"] == "balanced"
    assert rows["large-v3"]["downloaded"] is False and rows["large-v3"]["precision"] == "float16"
    assert rows["tiny"]["size"] == "75 MB"
