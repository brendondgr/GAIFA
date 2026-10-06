"""11.6: suggested inputs for each development workflow, scored against hand-written expectations
(tests/fixtures/expected/<name>.toml). `pytest -k detect -s` prints the score table."""

import json
import tomllib
from pathlib import Path

import pytest

from comfy.convert import to_api
from comfy.detect import suggest, to_toml
from comfy.nodes import NodeCatalog
from comfy.packs import Manifest
from scoring import line, load_expected, score

FIX = Path(__file__).parent / "fixtures"
CAT = NodeCatalog(json.loads((FIX / "object_info.json").read_text()))
NAMES = sorted(p.stem for p in (FIX / "expected").glob("*.toml"))
SCORES: dict[str, dict] = {}


def run(name: str):
    ed = json.loads((FIX / "workflows" / f"{name}.json").read_text())
    return suggest(to_api(ed, CAT), CAT, ed, name, {})


@pytest.mark.parametrize("name", NAMES)
def test_detect_matches_expected(name):
    s = run(name)
    sc = score(s.manifest, load_expected(FIX / "expected" / f"{name}.toml"))
    SCORES[name] = sc
    assert sc["task_ok"] and sc["outputs_ok"]
    assert not sc["wrong"] and not sc["extra"], sc
    known = set(load_expected(FIX / "expected" / f"{name}.toml").get("missed", {}))
    assert set(sc["missed"]) <= known, sc               # only the recorded misses


@pytest.mark.parametrize("name", NAMES)
def test_suggested_toml_is_a_valid_manifest(name):
    s = run(name)
    m = Manifest.model_validate(tomllib.loads(to_toml(s)))
    assert m.task == s.manifest["task"] and set(m.inputs) == set(s.manifest["inputs"])


def test_detect_score_table():
    for name in NAMES:
        SCORES.setdefault(name, score(run(name).manifest, load_expected(FIX / "expected" / f"{name}.toml")))
    print("\n" + "\n".join(line(n, SCORES[n]) for n in NAMES))
    total = {k: sum(len(SCORES[n][k]) for n in NAMES) for k in ("right", "wrong", "missed", "extra")}
    print(f"{'TOTAL':26} right {total['right']:2}  wrong {total['wrong']}  missed {total['missed']}  extra {total['extra']}")
