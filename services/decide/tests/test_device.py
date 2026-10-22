"""39.3: which device d3-lite loads on, per variant (no model: `device` alone)."""

from __future__ import annotations

from decide import device


def test_auto_follows_the_variant(monkeypatch):
    monkeypatch.setenv("AIHUB_DEVICE", "xpu")
    assert device.device("auto") == "xpu" and device.device("cpu") == "cpu"
    monkeypatch.delenv("AIHUB_DEVICE")
    monkeypatch.setattr(device, "available", lambda n: n in ("mps", "cpu"))
    assert device.device("auto") == "mps"


def test_empty_cache_without_torch_device_is_quiet():
    device.empty_cache("cpu")
    device.empty_cache("nope")
