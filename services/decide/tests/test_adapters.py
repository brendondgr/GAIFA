"""More decision models (plan capability-enablement 7.3): a card makes another model of a family usable with no code,
each model lists its judge cutoff, whether the judge's eval tuned it and its last test, and a folder no adapter reads
is shown with why and the fix."""

from __future__ import annotations

import httpx
from fastapi.testclient import TestClient

from decide.engine import Decider, LocalBackend
from decide.hubclient import Hub
from decide.models import ADAPTERS, CARD, D3Lite, card_class, unknown_folders, with_cards
from decide.models.fake import FakeModel
from decide.server import create_app

CARD_TEXT = """family = "fake"
id = "fake-small"
name = "Fake small"
repo = "test/fake-small"
revision = "1111111111111111111111111111111111111111"
weights = "small.bin"
threshold = 0.6
"""


def test_d3_lite_declares_its_cutoff():
    assert D3Lite.THRESHOLD == 0.35 and D3Lite.TUNED is True and D3Lite.FAMILY == "d3"


def test_a_card_is_its_familys_adapter_with_its_own_facts(tmp_path):
    cls = card_class({"family": "d3", "id": "d3-other", "repo": "x/d3-other", "revision": "a" * 40,
                      "weights": "m.safetensors", "pinned": {"modeling_d3.py": "b" * 64}})
    assert issubclass(cls, D3Lite) and cls.ID == "d3-other" and cls.FOLDER == "d3-other" and cls.THRESHOLD == 0.35
    assert cls.TUNED is False and cls.PINNED == {"modeling_d3.py": "b" * 64} and cls.load is D3Lite.load
    problems = cls.check(tmp_path)                  # the family's own check, against the card's pins
    assert problems and problems[0].startswith("no weights")
    for bad in ({"family": "nope", "id": "x", "repo": "a/b", "revision": "r", "weights": "w"},
                {"family": "d3", "repo": "a/b", "revision": "r", "weights": "w"}):
        try:
            card_class(bad)
        except ValueError:
            continue
        raise AssertionError(f"{bad} was accepted")


def test_cards_in_model_folders_and_unknown_folders(settings, hub):
    small = settings.models_dir / "fake-small"
    small.mkdir()
    (small / CARD).write_text(CARD_TEXT)
    other = settings.models_dir / "mystery"
    other.mkdir()
    (other / "model.safetensors").write_bytes(b"x")
    adapters = with_cards({"fake": FakeModel}, settings.models_dir)
    assert set(adapters) == {"fake", "fake-small"} and adapters["fake-small"].THRESHOLD == 0.6
    assert with_cards(ADAPTERS, settings.models_dir).keys() >= {"d3-lite"}      # a fake card needs the fake family
    unknown = unknown_folders(adapters, settings.models_dir)
    assert [u["id"] for u in unknown] == ["mystery"] and "gaifa setup --prompt decide" in unknown[0]["fix"]

    dec = Decider(LocalBackend({"fake": FakeModel}, settings.models_dir), settings.state_dir)
    app = create_app(settings, decider=dec, hub=Hub(settings.hub_url, transport=httpx.MockTransport(hub.handler)),
                     adapters={"fake": FakeModel})
    with TestClient(app) as c:
        listed = {m["id"]: m for m in c.get("/v1/models").json()["models"]}
        assert listed["fake-small"]["usable"] is False and listed["fake-small"]["threshold"] == 0.6
        assert listed["fake"]["threshold"] == 0.5 and listed["fake"]["tuned"] is False and listed["fake"]["test"] is None
        assert listed["mystery"]["usable"] is False and "no card" in listed["mystery"]["problems"][0]
        (small / "small.bin").write_bytes(b"w")       # its weights arrive: usable, and it answers
        listed = {m["id"]: m for m in c.get("/v1/models").json()["models"]}
        assert listed["fake-small"]["usable"] is True
        r = c.post("/v1/decide", json={"input": "the sky", "model": "fake-small",
                                       "questions": [{"id": "q", "type": "yesno", "question": "sky? [yes_if: sky]"}]})
        assert r.status_code == 200, r.text
        assert r.json()["model"] == "fake-small" and r.json()["answers"]["q"]["top"] == "yes"
        assert FakeModel.loads[-1].endswith("fake-small")
        # a test is kept per model and shown beside it
        t = c.post("/v1/selftest", json={"model": "fake-small"}).json()
        assert t["passed"] is True and t["model"] == "fake-small"
        listed = {m["id"]: m for m in c.get("/v1/models").json()["models"]}
        assert listed["fake-small"]["test"]["sentence"] == t["sentence"] and listed["fake"]["test"] is None
