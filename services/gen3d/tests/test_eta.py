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


# ---- image engines (plan 17.7) -------------------------------------------------------------------

def _total(e, raw, loaded=frozenset(), up=False):
    req = parse_request({"image": "output:o", **raw})
    return req, e.plan(req, req.stages, set(loaded), up)


def test_hunyuan_fast_matches_the_lab(tmp_path):
    e = _est(tmp_path)
    _, plan = _total(e, {"engine": "hunyuan21", "stages": ["shape"]})
    assert [p["sub"] for p in plan] == ["worker.start", "load.hunyuan21", "hunyuan.conditioning", "hunyuan.diffusion",
                                        "hunyuan.decode", "hunyuan.post"]
    assert 95 < sum(p["seconds"] for p in plan) < 125                   # real: 110 s cold (2026-10-11)
    _, base = _total(e, {"engine": "hunyuan21", "preset": "base", "stages": ["shape"]}, {"hunyuan21"}, True)
    assert 290 < sum(p["seconds"] for p in base) < 340                  # lab: 317 s warm
    _, warm = _total(e, {"engine": "hunyuan21", "stages": ["shape"]}, {"hunyuan21"}, True)
    assert "load.hunyuan21" not in {p["sub"] for p in warm}


def test_sam3d_objects_and_delegated_engines(tmp_path):
    e = _est(tmp_path)
    _, s3o = _total(e, {"engine": "sam3d_objects", "stages": ["shape"]}, {"sam3d_objects"}, True)
    assert 30 < sum(p["seconds"] for p in s3o) < 70                     # real: 49 s warm on the vase
    _, tr = _total(e, {"engine": "trellis2", "stages": ["shape"]})
    assert [p["sub"] for p in tr] == ["trellis2.comfy"]                  # no gen3d worker for a delegated engine
    _, draft = _total(e, {"engine": "trellis2", "preset": "draft", "stages": ["shape"]})
    _, base = _total(e, {"engine": "trellis2", "preset": "base", "stages": ["shape"]})
    assert draft[0]["seconds"] < tr[0]["seconds"] < base[0]["seconds"]
    _, body = _total(e, {"engine": "sam3d_body", "stages": ["shape"]})
    assert body[0]["sub"] == "sam3d_body.comfy" and body[0]["seconds"] < 15


def test_learned_times_are_per_setting(tmp_path):
    e = _est(tmp_path)
    req, _ = _total(e, {"engine": "trellis2", "stages": ["shape"]})
    feats = {"res": 1024, "shape": 12, "refine": 6, "lowpoly": False}
    for s in (230, 235, 240):
        e.record("trellis2.comfy", feats, s)
    assert e.plan(req, ["shape"], set(), True)[0]["seconds"] == 235
    _, lowpoly = _total(e, {"engine": "trellis2", "stages": ["shape"], "trellis2": {"target_faces": 50000}})
    assert lowpoly[0]["seconds"] != 235                                 # another setting: still the seeded default
