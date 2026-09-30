import time

from gen3d.eta import Estimator, _interp_log, SHAPE_DECODE
from gen3d.options import parse_request
from gen3d.store import Store


def _est(tmp_path):
    return Estimator(Store(tmp_path / "t.db", tmp_path / "jobs"))


def test_decode_interpolation_is_log_linear():
    assert _interp_log(SHAPE_DECODE, 8.0) == SHAPE_DECODE[8.0]
    mid = _interp_log(SHAPE_DECODE, 8.5)
    assert SHAPE_DECODE[8.0] < mid < SHAPE_DECODE[9.0]
    assert abs(mid - (SHAPE_DECODE[8.0] * SHAPE_DECODE[9.0]) ** 0.5) < 1e-6


def test_loaded_models_and_worker_skip_load_time(tmp_path):
    e = _est(tmp_path)
    req = parse_request({"prompt": "x", "stages": ["shape", "parts"], "parts": {"parts": ["a", "b"]}})
    cold = sum(p["seconds"] for p in e.plan(req, req.stages, set(), False))
    warm = sum(p["seconds"] for p in e.plan(req, req.stages, {"shape", "parts"}, True))
    assert cold - warm > 50
    subs = [p["sub"] for p in e.plan(req, req.stages, set(), False)]
    assert subs[:2] == ["worker.start", "load.shape"] and "load.parts" in subs


def test_learning_replaces_defaults(tmp_path):
    e = _est(tmp_path)
    req = parse_request({"prompt": "x"})
    for s in (40, 42, 41):
        e.record("shape.gpt", {"fast": False}, s)
    gpt = next(p for p in e.plan(req, ["shape"], {"shape"}, True) if p["sub"] == "shape.gpt")
    assert gpt["seconds"] == 41


def test_live_rate_drives_running_substage(tmp_path):
    e = _est(tmp_path)
    req = parse_request({"prompt": "x", "stages": ["shape"]})
    job = {"stages": {"shape": {"state": "running", "sub": "shape.gpt", "step": 512, "total": 1024,
                                "sub_started": time.time() - 10}}}
    rem = e.remaining(job, req, {"shape"}, True)
    # 10 s for half the tokens -> ~10 s left, plus decode + post
    assert 30 < rem["eta_s"] < 45


def test_worker_start_counts_the_whole_running_stage(tmp_path):
    e = _est(tmp_path)
    req = parse_request({"prompt": "x", "stages": ["shape", "preview"]})
    job = {"stages": {"shape": {"state": "running", "sub": "worker.start", "sub_started": time.time()},
                      "preview": {"state": "pending"}}}
    rem = e.remaining(job, req, set(), False)
    assert rem["by_stage"]["shape"] > 90  # load + gpt + decode + post, not just the preview
