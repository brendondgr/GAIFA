import pytest
from pydantic import ValidationError

from gen3d.options import MAX_PARTS, catalogue, parse_request


def test_preset_merges_under_explicit_values():
    r = parse_request({"prompt": "x", "preset": "fast", "parts": {"parts": ["a"], "steps": 40}, "stages": ["shape", "parts"]})
    assert r.shape.resolution_base == 7.5      # from the preset
    assert r.parts.steps == 40                 # explicit wins
    assert r.parts.resolution_base == 8.0      # from the preset


def test_stages_are_deduped_and_ordered():
    r = parse_request({"prompt": "x", "stages": ["preview", "shape", "shape"]})
    assert r.stages == ["shape", "preview"]


@pytest.mark.parametrize("raw", [
    {"stages": ["shape"]},                                            # shape needs a prompt
    {"prompt": "x", "stages": ["parts"]},                             # parts needs names
    {"prompt": "x", "parts": {"parts": ["p"] * (MAX_PARTS + 1)}},     # too many parts
    {"prompt": "x", "shape": {"resolution_base": 12}},                # out of range
    {"prompt": "x", "shape": {"bbox": [1, 0, 1]}},                    # degenerate bbox
    {"prompt": "x", "stages": []},
])
def test_invalid_requests(raw):
    with pytest.raises(ValidationError):
        parse_request(raw)


def test_catalogue_has_bounds_and_defaults():
    c = catalogue()
    f = {(x["group"], x["key"]): x for x in c["fields"]}
    assert f[("parts", "steps")]["min"] == 5 and f[("parts", "steps")]["default"] == 50
    assert c["defaults"]["stages"] == ["shape", "preview"]
    assert set(c["presets"]) == {"lowpoly", "fast", "balanced", "quality"}


def test_lowpoly_preset_sets_face_budgets():
    r = parse_request({"prompt": "x", "preset": "lowpoly", "stages": ["shape", "parts"], "parts": {"parts": ["a"]}})
    assert r.shape.target_faces == 1000 and r.parts.target_faces == 1000 and r.rig.target_faces == 1000
    assert r.shape.resolution_base == 7.0 and r.parts.resolution_base == 7.0
    assert parse_request({"prompt": "x"}).shape.target_faces is None  # full detail by default


# ---- image engines (plan 17.3) -------------------------------------------------------------------

def test_old_requests_parse_as_cube3d():
    r = parse_request({"prompt": "a fox", "preset": "balanced"})
    assert r.engine == "cube3d" and r.image is None and r.preset == "balanced"


@pytest.mark.parametrize("engine", ["hunyuan21", "trellis2", "sam3d_objects", "sam3d_body"])
def test_image_engines_default_to_their_fast_preset(engine):
    r = parse_request({"engine": engine, "image": "output:o_123"})
    assert r.preset == "fast" and r.prompt == ""
    base = parse_request({"engine": engine, "image": "output:o_123", "preset": "base"})
    assert getattr(base, engine) != getattr(r, engine)            # base differs from fast somewhere


def test_image_presets_merge_under_explicit_values():
    r = parse_request({"engine": "hunyuan21", "image": "output:o", "preset": "base", "hunyuan21": {"steps": 40}})
    assert r.hunyuan21.steps == 40 and r.hunyuan21.flashvdm is False and r.hunyuan21.num_chunks == 8000
    r = parse_request({"engine": "trellis2", "image": "output:o", "preset": "draft"})
    assert r.trellis2.resolution == 512
    r = parse_request({"engine": "trellis2", "image": "output:o"})
    assert (r.trellis2.shape_steps, r.trellis2.refine_steps, r.trellis2.target_faces) == (12, 6, 0)


@pytest.mark.parametrize("raw", [
    {"engine": "hunyuan21"},                                                    # no picture
    {"engine": "trellis2", "image": "output:o", "preset": "lowpoly"},          # a Cube3D preset
    {"engine": "trellis2", "image": "/etc/passwd"},                             # only output ids or uploads
    {"engine": "hunyuan21", "image": "output:o", "hunyuan21": {"octree": 300}},  # not a choice
    {"engine": "sam3d_objects", "image": "output:o", "sam3d_objects": {"target_faces": -1}},
    {"engine": "nope", "image": "output:o"},
])
def test_invalid_image_requests(raw):
    with pytest.raises(ValidationError):
        parse_request(raw)


def test_catalogue_lists_engines_with_presets_and_settings():
    c = {e["id"]: e for e in catalogue()["engines"]}
    assert list(c) == ["cube3d", "hunyuan21", "trellis2", "sam3d_objects", "sam3d_body"]
    assert c["trellis2"]["runs_in"] == "comfy" and c["hunyuan21"]["runs_in"] == "gen3d"
    assert set(c["trellis2"]["presets"]) == {"fast", "base", "draft"} and c["trellis2"]["default_preset"] == "fast"
    f = {x["key"]: x for x in c["hunyuan21"]["fields"]}
    assert f["octree"]["choices"] == [256, 384, 512] and f["steps"]["min"] == 5 and f["steps"]["default"] == 30
    assert f["target_faces"]["default"] == 0 and 50_000 in f["target_faces"]["shortcuts"]
    assert "target_faces" not in {x["key"] for x in c["sam3d_body"]["fields"]}   # a fixed rigged mesh
    assert all(e["license"] for e in c.values())


def test_a_picture_without_an_engine_uses_trellis2():
    r = parse_request({"image": "output:o"})
    assert r.engine == "trellis2" and r.preset == "fast"
    assert parse_request({"engine": "hunyuan21", "image": "15c9f40a9a36"}).image == "output:15c9f40a9a36"   # a bare output id


# ---- capabilities in the schema (plan 20.2) --------------------------------------------------

def _x_options():
    from gen3d.options import JobRequest
    props = JobRequest.model_json_schema()["properties"]
    return props["engine"]["x-options"], props["preset"]


def test_engine_options_say_what_each_engine_takes():
    from gen3d.engines import ENGINES, IMAGE_ENGINES
    from gen3d.image_options import IMAGE_PRESETS
    from gen3d.options import PRESETS
    o, preset = _x_options()
    assert set(o) == set(ENGINES)
    assert o["cube3d"]["excludes"] == ["image"] and o["cube3d"]["default"] and "needs" not in o["cube3d"]
    assert o["cube3d"]["allows"]["preset"] == list(PRESETS)
    for eid in IMAGE_ENGINES:
        assert o[eid]["needs"] == ["image"] and o[eid]["allows"]["preset"] == list(IMAGE_PRESETS[eid]) and o[eid]["label"]
    assert [k for k, v in o.items() if v.get("default")] == ["cube3d", "trellis2"]     # one per input combination
    assert preset["x-depends-on"] == "engine" and set(preset["anyOf"][0]["enum"]) >= {"fast", "base", "draft", "balanced"}


def test_cube3d_with_a_picture_is_refused_with_the_image_engines():
    from gen3d.options import Refusal
    with pytest.raises(ValidationError) as e:
        parse_request({"engine": "cube3d", "prompt": "a fox", "image": "output:abc"})
    err = e.value.errors()[0]["ctx"]["error"]
    assert isinstance(err, Refusal) and "can't use a picture" in str(err) and "trellis2" in err.fix and "hunyuan21" in err.fix


def test_an_image_engine_without_a_picture_says_to_make_one_first():
    with pytest.raises(ValidationError) as e:
        parse_request({"engine": "trellis2", "prompt": "a fox"})
    err = e.value.errors()[0]["ctx"]["error"]
    assert "give `image`" in str(err) and "comfy_generate_image" in err.fix and "cube3d" in err.fix


def test_a_wrong_preset_names_the_engines_presets():
    with pytest.raises(ValidationError) as e:
        parse_request({"engine": "hunyuan21", "image": "output:abc", "preset": "draft"})
    assert e.value.errors()[0]["ctx"]["error"].fix == "use one of: fast, base"


def test_no_engine_is_cube3d_without_a_picture():
    assert parse_request({"prompt": "a fox"}).engine == "cube3d"
