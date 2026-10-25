"""38.1: the setup block's version 3: variants per accelerator and the smoke."""

from __future__ import annotations

import pytest

from utils.setupdocs.block import Variant, read


def ok(data: dict):
    setup, problem = read(data)
    assert problem is None, problem
    return setup


def test_variants_parse():
    s = ok({"summary": "x", "smoke": "gaifa smoke tts", "variants": [
        {"accel": "rocm", "tested": True, "env": {"HSA": "1"}},
        {"accel": "cuda", "os": ["linux", "wsl"], "steps": [{"run": "./install.sh --accel cuda", "what": "torch cu128"}], "note": "untested"},
        {"accel": "cpu", "os": ["linux", "wsl", "darwin"], "tested": ["linux"], "check": "true", "smoke": "echo hi"},
    ]})
    rocm, cuda, cpu = s.variants
    assert (rocm.os, rocm.tested, rocm.env, rocm.steps) == (["linux"], ["linux"], {"HSA": "1"}, None)
    assert cuda.tested == [] and cuda.steps[0].run == "./install.sh --accel cuda" and cuda.note == "untested"
    assert cpu.tested == ["linux"] and (cpu.check, cpu.smoke) == ("true", "echo hi")
    assert s.smoke == "gaifa smoke tts" and s.gpu is True and s.runs_on() == ["rocm", "cuda", "cpu"]


def test_version_2_blocks_stand_for_one_variant():
    assert ok({"summary": "x", "gpu": False}).effective_variants() == [Variant("cpu", ["linux", "wsl", "darwin"], ["linux"])]
    assert ok({"summary": "x", "gpu": True}).effective_variants() == [Variant("rocm", ["linux"], ["linux"])]
    assert ok({"summary": "x"}).runs_on() == ["cpu"]
    assert ok({"variants": [{"accel": "cpu"}]}).gpu is False


@pytest.mark.parametrize("bad, msg", [
    ({"variants": [{"accel": "metal"}]}, "`accel` must be one of"),
    ({"variants": [{"accel": "cuda", "os": ["windows"]}]}, "`os` must be a list"),
    ({"variants": [{"accel": "cuda", "tested": ["mac"]}]}, "`tested` must be"),
    ({"variants": [{"accel": "cuda", "env": {"A": 1}}]}, "`env` must be a table"),
    ({"variants": [{"accel": "cuda", "steps": [{"run": "x"}]}]}, "variants[0].steps[0]: `what`"),
    ({"variants": [{"accel": "cuda", "gpu": True}]}, "unknown key(s) gpu"),
    ({"variants": {"accel": "cuda"}}, "`variants` must be an array"),
    ({"smoke": ""}, "`smoke` must be a non-empty command"),
    ({"variants": [{"accel": "cpu", "needs": "uv"}]}, "`needs` must be a list"),
])
def test_bad_variants(bad, msg):
    setup, problem = read(bad)
    assert setup is None and msg in problem


def test_variant_needs():
    s = ok({"needs": ["systemd-run"], "variants": [{"accel": "mps", "os": ["darwin"], "needs": ["uv"]}, {"accel": "cpu"}]})
    assert s.variants[0].needs == ["uv"] and s.variants[1].needs is None
