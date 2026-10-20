"""The gfx1151 guard: int8 `small` and up on an AMD GPU faults the process, so it is refused before
the load (the prototype's `unsafe_combination`)."""

from __future__ import annotations

import pytest

from stt.asr import acceleration
from stt.asr.contract import AsrLoadError
from stt.asr.faster_whisper import FasterWhisperBackend


@pytest.fixture
def amd(monkeypatch):
    monkeypatch.setattr(acceleration, "detect_hardware", lambda: "rocm")
    monkeypatch.delenv(acceleration.UNSAFE_OVERRIDE, raising=False)


@pytest.mark.parametrize("model", ["small", "medium", "large-v3-turbo", "large-v3", "/models/stt/small"])
def test_int8_small_and_up_on_an_amd_gpu_is_refused(amd, model):
    assert "memory fault" in acceleration.unsafe_combination("cuda", "int8", model)
    assert acceleration.unsafe_combination("auto", "int8", model)


@pytest.mark.parametrize(("device", "precision", "model"), [
    ("cuda", "int8", "tiny"), ("cuda", "int8", "base"), ("cuda", "float16", "small"),
    ("cpu", "int8", "large-v3"), ("cuda", "float16", "large-v3")])
def test_the_combinations_that_work_pass(amd, device, precision, model):
    assert acceleration.unsafe_combination(device, precision, model) == ""


def test_other_hardware_is_not_guarded(monkeypatch):
    monkeypatch.setattr(acceleration, "detect_hardware", lambda: "cuda")
    assert acceleration.unsafe_combination("cuda", "int8", "small") == ""


def test_the_override_lets_it_through(amd, monkeypatch):
    monkeypatch.setenv(acceleration.UNSAFE_OVERRIDE, "1")
    assert acceleration.unsafe_combination("cuda", "int8", "small") == ""


def test_the_backend_refuses_before_the_model_is_touched(amd):
    built = []
    backend = FasterWhisperBackend(model="small", device="cuda", precision="int8",
                                   model_factory=lambda *a, **k: built.append(a))
    with pytest.raises(AsrLoadError, match="memory fault"):
        backend.load()
    assert built == []


def test_the_backend_loads_from_its_folder(tmp_path):
    seen = {}

    def factory(source, **kwargs):
        seen.update(source=source, **kwargs)
        return object()

    FasterWhisperBackend(model="small", device="cpu", precision="int8", model_factory=factory,
                         model_path=str(tmp_path / "small")).load()
    assert seen["source"] == str(tmp_path / "small")
    assert seen["compute_type"] == "int8" and seen["device"] == "cpu"


def test_a_kept_wheel_is_matched_on_version_and_python(tmp_path):
    import sys

    tag = f"cp{sys.version_info.major}{sys.version_info.minor}"
    (tmp_path / f"ctranslate2-4.8.1-{tag}-{tag}-manylinux_2_28_x86_64.whl").write_bytes(b"")
    (tmp_path / f"ctranslate2-4.8.1-{tag}t-{tag}t-manylinux_2_28_x86_64.whl").write_bytes(b"")
    found = acceleration.kept_wheel("4.8.1", tmp_path)
    assert found is not None and f"{tag}-{tag}-" in found.name
    assert acceleration.kept_wheel("4.7.0", tmp_path) is None
