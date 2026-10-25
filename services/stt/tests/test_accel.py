"""39.5: the variant the hub passes decides which CTranslate2 build stt counts on."""

from __future__ import annotations

from stt.asr import acceleration


def test_the_variant_wins(monkeypatch):
    for accel, want in (("rocm", "rocm"), ("cuda", "cuda"), ("cpu", "none"), ("xpu", "none"), ("mps", "none")):
        monkeypatch.setenv("GAIFA_ACCEL", accel)
        assert acceleration.detect_hardware() == want


def test_without_one_it_reads_the_kernel(monkeypatch, tmp_path):
    monkeypatch.delenv("GAIFA_ACCEL", raising=False)
    monkeypatch.setattr(acceleration, "KFD_NODE", tmp_path / "kfd")
    monkeypatch.setattr(acceleration, "DRM_DIR", tmp_path / "drm")
    assert acceleration.detect_hardware() in ("cuda", "none")      # cuda only on a machine with NVIDIA's driver
    (tmp_path / "kfd").write_text("")
    if acceleration.detect_hardware() != "cuda":
        assert acceleration.detect_hardware() == "rocm"


def test_int8_guard_follows_the_variant(monkeypatch):
    monkeypatch.setenv("GAIFA_ACCEL", "cuda")
    assert acceleration.unsafe_combination("cuda", "int8", "large-v3") == ""      # the AMD-only crash guard is off
    monkeypatch.setenv("GAIFA_ACCEL", "rocm")
    assert "AMD GPU" in acceleration.unsafe_combination("cuda", "int8", "large-v3")
