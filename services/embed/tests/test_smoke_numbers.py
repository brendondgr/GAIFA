"""capability-enablement 7.2: the encoder's test reports numbers, not only pass: the first text, forty more, texts a
second, the device and the memory, in one sentence."""

from __future__ import annotations


def test_selftest_measures(client):
    r = client.post("/v1/selftest")
    assert r.status_code == 200, r.text
    t = r.json()
    assert t["passed"] is True and t["device"] == "cpu" and t["texts_per_s"] >= 0 and t["first_s"] >= 0
    assert " on the CPU: " in t["sentence"] and "texts a second" in t["sentence"] and t["sentence"].endswith(" GB")
