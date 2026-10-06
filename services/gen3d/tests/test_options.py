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
