"""39.3: which device and dtype the encoder takes, per variant (a fake torch; no model)."""

from __future__ import annotations

import pytest

from embed import device, encoder


class FakeTorch:
    float32, bfloat16 = "float32", "bfloat16"

    class cuda:
        @staticmethod
        def is_bf16_supported() -> bool:
            return True


@pytest.fixture
def reach(monkeypatch):
    def set_(*names):
        monkeypatch.setattr(device, "available", lambda n: n in names or n == "cpu")
    return set_


def test_auto_follows_the_variant(monkeypatch, reach):
    reach("cuda", "xpu")
    for accel_device, want in (("cuda", ("cuda", "bfloat16")), ("xpu", ("xpu", "bfloat16")), ("cpu", ("cpu", "float32"))):
        monkeypatch.setenv("AIHUB_DEVICE", accel_device)
        assert encoder.choose("auto", FakeTorch) == want


def test_auto_without_a_variant_takes_what_torch_reaches(monkeypatch, reach):
    monkeypatch.delenv("AIHUB_DEVICE", raising=False)
    reach("mps")
    assert encoder.choose("auto", FakeTorch) == ("mps", "float32")
    reach()
    assert encoder.choose("auto", FakeTorch) == ("cpu", "float32")


def test_asked_for_and_missing(monkeypatch, reach):
    monkeypatch.setenv("AIHUB_DEVICE", "cuda")
    reach()
    assert encoder.choose("auto", FakeTorch) == ("cpu", "float32")          # the variant's device is gone: the CPU
    with pytest.raises(RuntimeError, match="EMBED_DEVICE=cuda"):
        encoder.choose("cuda", FakeTorch)
    assert encoder.choose("cpu", FakeTorch) == ("cpu", "float32")
