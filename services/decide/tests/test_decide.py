"""POST /v1/decide with the fake model: each question type, batching, per-question errors, validation, images,
load and unload, the models list."""

from __future__ import annotations

from tests.conftest import png


def ask(client, questions, input="the user asked to run the tests", **kw):
    return client.post("/v1/decide", json={"input": input, "questions": questions, **kw})


def test_yesno(client):
    r = ask(client, [{"id": "tests", "type": "yesno", "question": "Is this about tests? [yes_if: tests]"},
                     {"id": "rm", "type": "yesno", "question": "Does it delete? [yes_if: delete]"}])
    assert r.status_code == 200, r.text
    a = r.json()["answers"]
    assert a["tests"] == {"probs": {"yes": 0.97, "no": 0.03}, "top": "yes", "p": 0.97}
    assert a["rm"]["top"] == "no" and abs(a["rm"]["p"] - 0.9) < 1e-6
    assert r.json()["model"] == "fake" and "ms" in r.json()


def test_choice_with_names_and_descriptions(client):
    r = ask(client, [{"id": "kind", "type": "choice", "question": "What is it?", "options": ["edit", "tests", "net"]},
                     {"id": "kind2", "type": "choice", "question": "What is it?",
                      "options": {"read": "only reads", "tests": "runs tests"}}])
    a = r.json()["answers"]
    assert a["kind"]["top"] == "tests" and set(a["kind"]["probs"]) == {"edit", "tests", "net"}
    assert abs(sum(a["kind"]["probs"].values()) - 1) < 1e-6
    assert a["kind2"]["top"] == "tests"


def test_score(client):
    r = ask(client, [{"id": "risk", "type": "score", "question": "How risky?", "scale": ["none", "some", "tests"]}])
    a = r.json()["answers"]["risk"]
    assert a["top"] == "tests" and list(a["probs"]) == ["none", "some", "tests"]
    assert abs(a["value"] - (0.1 * 1 + 0.8 * 2)) < 1e-6


def test_json_input(client):
    r = ask(client, [{"id": "q", "type": "yesno", "question": "tool? [yes_if: bash]"}],
            input={"tool": "bash", "command": "ls"})
    assert r.json()["answers"]["q"]["top"] == "yes"


def test_questions_go_together_in_batches(client):
    qs = [{"id": f"q{i}", "type": "yesno", "question": f"q {i}?"} for i in range(20)]
    r = ask(client, qs)
    assert r.status_code == 200 and len(r.json()["answers"]) == 20
    from decide.models.fake import FakeModel
    assert len(FakeModel.calls) == 1 and FakeModel.calls[0]["batches"] == 3      # 8 + 8 + 4 per forward pass
    assert ask(client, qs * 2).status_code == 422                                # duplicate ids
    many = [{"id": f"q{i}", "type": "yesno", "question": "x"} for i in range(33)]
    r = ask(client, many)
    assert r.status_code == 413 and r.json()["code"] == "too_many"


def test_one_question_failing_leaves_the_rest(client):
    r = ask(client, [{"id": "long", "type": "yesno", "question": "[too long]"},
                     {"id": "ok", "type": "yesno", "question": "fine? [yes_if: tests]"}])
    a = r.json()["answers"]
    assert a["long"] == {"error": "max_length_exceeded", "message": "over the input limit"}
    assert a["ok"]["top"] == "yes"


def test_a_model_error_is_not_a_dead_worker(client):
    r = ask(client, [{"id": "q", "type": "yesno", "question": "tests? [yes_if: tests]"}], input="[gpu error] tests")
    assert r.status_code == 503 and r.json()["code"] == "model_error" and r.json()["fix"], r.text
    assert ask(client, [{"id": "q", "type": "yesno", "question": "tests? [yes_if: tests]"}]).status_code == 200


def test_validation(client):
    bad = [
        [{"id": "c", "type": "choice", "question": "x", "options": ["only one"]}],
        [{"id": "c", "type": "choice", "question": "x"}],
        [{"id": "s", "type": "score", "question": "x", "scale": ["a", "a"]}],
        [{"id": "y", "type": "yesno", "question": "x", "options": ["a", "b"]}],
        [{"id": "bad id!", "type": "yesno", "question": "x"}],
        [{"id": "t", "type": "maybe", "question": "x"}],
        [],
    ]
    for qs in bad:
        assert ask(client, qs).status_code == 422, qs
    r = ask(client, [{"id": "q", "type": "yesno", "question": "x"}], input="x" * 100_001)
    assert r.status_code == 413 and r.json()["code"] == "too_large"


def test_images_from_outputs(client, hub):
    img = hub.add("img1", "image", png())
    r = ask(client, [{"id": "q", "type": "yesno", "question": "x"}], images=[img])
    assert r.status_code == 200
    from decide.models.fake import FakeModel
    assert FakeModel.calls[-1]["images"] == 1
    aud = hub.add("aud1", "audio", b"RIFF")
    r = ask(client, [{"id": "q", "type": "yesno", "question": "x"}], images=[aud])
    assert r.status_code == 422 and r.json()["code"] == "wrong_kind"
    r = ask(client, [{"id": "q", "type": "yesno", "question": "x"}], videos=[hub.add("v", "video", b"x")])
    assert r.status_code == 422 and r.json()["code"] == "unsupported_input"     # the fake reads no video
    assert ask(client, [{"id": "q", "type": "yesno", "question": "x"}], images=["output:nope"]).status_code == 404


def test_load_unload_and_status(client, decider):
    s = client.get("/v1/status").json()
    assert s["loaded"] is False and s["stats"][0]["label"] == "Calls today"
    r = client.post("/v1/load", json={})
    assert r.status_code == 200 and r.json()["loaded"] == "fake"
    assert client.get("/v1/status").json()["loaded"] is True
    assert client.post("/v1/unload").json() == {"unloaded": True}
    assert client.get("/v1/status").json()["loaded"] is False
    assert client.post("/v1/unload").json() == {"unloaded": False}
    ask(client, [{"id": "q", "type": "yesno", "question": "x"}])                  # loads on first use
    assert decider.loaded and decider.calls == 1
    assert not decider.idle_due(0) and decider.idle_due(1, now=decider.last_used + 2)


def test_models_list_and_unknown_model(client, hub):
    m = client.get("/v1/models").json()["models"]
    assert m[0]["id"] == "fake" and m[0]["usable"] is True and m[0]["default"] is True
    r = ask(client, [{"id": "q", "type": "yesno", "question": "x"}], model="nope")
    assert r.status_code == 404 and r.json()["code"] == "unknown_model" and "fake" in r.json()["fix"]
    assert hub.models and hub.models[0]["path"] == "decide/fake"                # registered at start


def test_openapi_has_the_tool_route(client):
    spec = client.get("/openapi.json").json()
    assert "/v1/decide" in spec["paths"] and "post" in spec["paths"]["/v1/decide"]
