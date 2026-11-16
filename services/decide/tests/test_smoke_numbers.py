"""capability-enablement 7.2: the test reports numbers, not only pass: the first answer, ten more, the device and the
memory, in one sentence."""

from __future__ import annotations


def test_selftest_measures(client):
    r = client.post("/v1/selftest", json={})
    assert r.status_code == 200, r.text
    t = r.json()
    assert t["passed"] is True and t["model"] == "fake" and t["device"] == "cpu"
    assert t["first_s"] >= 0 and t["next10_s"] >= 0 and t["per_answer_s"] == round(t["next10_s"] / 10, 3)
    assert t["sentence"].startswith("fake on the CPU: ") and t["sentence"].endswith(" GB") and "per answer" in t["sentence"]


def test_unknown_model(client):
    r = client.post("/v1/selftest", json={"model": "nope"})
    assert r.status_code >= 400
