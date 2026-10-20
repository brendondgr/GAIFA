"""POST /v1/embed with the fake backend: each kind, prompts, Matryoshka sizes, batching, lazy encoders, unload."""

from __future__ import annotations

import numpy as np

from embed.encoder import QUERY_PROMPT, Encoder, FakeBackend, prompt, truncate
from tests.conftest import mp4, png, wav


def vecs(r) -> np.ndarray:
    assert r.status_code == 200, r.text
    return np.array(r.json()["vectors"], dtype=np.float32)


def test_text_query_and_document_prompts(client, backend):
    seen = []
    orig = backend.encode
    backend.encode = lambda kind, items, bs: (seen.extend(items), orig(kind, items, bs))[1]
    client.post("/v1/embed", json={"inputs": [{"text": "red car"}], "task": "query"})
    client.post("/v1/embed", json={"inputs": [{"text": "A red car.", "title": "Cars"}, {"text": "soup"}]})
    assert seen == [QUERY_PROMPT + "red car", "title: Cars | text: A red car.", "title: none | text: soup"]
    assert prompt("x", "document", "  ") == "title: none | text: x"


def test_image_audio_video_from_outputs(client, hub, tmp_path):
    img = hub.add("img1", "image", png("red car"))
    aud = hub.add("aud1", "audio", wav(2.5))
    vid = hub.add("vid1", "video", mp4(tmp_path, 4))
    r = client.post("/v1/embed", json={"inputs": [{"image": img}, {"audio": aud}, {"video": vid}, {"audio": vid}]})
    v = vecs(r)
    assert v.shape == (4, 768)
    info = r.json()["inputs"]
    assert [i["kind"] for i in info] == ["image", "audio", "video", "audio"]
    assert info[0] == {"kind": "image", "width": 64, "height": 48, "output": "img1"}
    assert info[1]["seconds"] == 2.5 and "truncated" not in info[1]
    assert info[2]["frames"] == 4 and info[2]["fps"] == 1.0
    assert abs(info[3]["seconds"] - 4) < 0.1                          # a video's soundtrack, as audio


def test_text_ranks_matching_image_first(client, hub):
    refs = [hub.add(f"i{n}", "image", png(label)) for n, label in enumerate(["a dog", "red car", "a bowl of soup"])]
    images = vecs(client.post("/v1/embed", json={"inputs": [{"image": r} for r in refs]}))
    query = vecs(client.post("/v1/embed", json={"inputs": [{"text": "red car"}], "task": "query"}))
    assert int(np.argmax(images @ query[0])) == 1


def test_order_is_kept_across_kinds(client, hub):
    img = hub.add("img1", "image", png("cat"))
    mixed = vecs(client.post("/v1/embed", json={"inputs": [{"text": "one"}, {"image": img}, {"text": "two"}]}))
    alone = vecs(client.post("/v1/embed", json={"inputs": [{"text": "two"}, {"text": "one"}]}))
    assert np.allclose(mixed[0], alone[1]) and np.allclose(mixed[2], alone[0])
    assert np.allclose(mixed[1], vecs(client.post("/v1/embed", json={"inputs": [{"image": "img1"}]}))[0])


def test_matryoshka_truncation_renormalizes(client):
    full = vecs(client.post("/v1/embed", json={"inputs": [{"text": "hello"}]}))[0]
    for dim in (512, 256, 128):
        v = vecs(client.post("/v1/embed", json={"inputs": [{"text": "hello"}], "dim": dim}))[0]
        assert v.shape == (dim,)
        assert abs(np.linalg.norm(v) - 1) < 1e-4
        assert np.allclose(v, full[:dim] / np.linalg.norm(full[:dim]), atol=1e-5)
    assert client.post("/v1/embed", json={"inputs": [{"text": "x"}], "dim": 300}).status_code == 422
    assert np.allclose(truncate(np.zeros((1, 768)), 128), 0)           # a zero vector stays zero, no NaN


def test_batching(client, backend, hub):
    vecs(client.post("/v1/embed", json={"inputs": [{"text": f"t{i}"} for i in range(70)]}))
    assert backend.batches == [("text", 32), ("text", 32), ("text", 6)]
    backend.batches.clear()
    refs = [hub.add(f"i{n}", "image", png(f"x{n}")) for n in range(6)]
    vecs(client.post("/v1/embed", json={"inputs": [{"image": r} for r in refs]}))
    assert backend.batches == [("image", 4), ("image", 2)]


def test_encoders_load_on_first_use_and_unload(client, backend, hub):
    assert client.get("/v1/status").json()["loaded"] is False
    vecs(client.post("/v1/embed", json={"inputs": [{"text": "x"}]}))
    assert backend.loads == [frozenset()]                              # the text path alone
    vecs(client.post("/v1/embed", json={"inputs": [{"image": hub.add("i", "image", png("x"))}]}))
    assert backend.loads[-1] == {"vision"}
    vecs(client.post("/v1/embed", json={"inputs": [{"text": "y"}]}))
    assert len(backend.loads) == 2                                     # nothing reloads for text
    vecs(client.post("/v1/embed", json={"inputs": [{"audio": hub.add("a", "audio", wav(1))}]}))
    assert backend.loads[-1] == {"vision", "audio"}                    # the union: vision stays
    st = client.get("/v1/status").json()
    assert st["loaded"] is True and {"label": "Loaded", "value": "text, audio, vision"} in st["stats"]
    assert client.post("/v1/unload").json() == {"unloaded": True}
    assert backend.parts is None and client.get("/v1/status").json()["loaded"] is False
    assert client.post("/v1/unload").json() == {"unloaded": False}
    assert client.post("/v1/load", json={"kinds": ["video"]}).json()["loaded"] == "text+vision"


def test_extra_encoder_asks_hub_for_memory(client, hub):
    client.post("/v1/load")
    assert hub.acquires == []                                          # a load from unloaded: [memory] triggers
    hub.room = False
    r = client.post("/v1/embed", json={"inputs": [{"image": hub.add("i", "image", png("x"))}]})
    assert r.status_code == 409 and r.json()["code"] == "needs_room" and "plan" in r.json()["data"]
    assert hub.acquires[0]["service"] == "embed" and hub.acquires[0]["needs_bytes"] > 0


def test_measured_memory_is_kept(settings, backend):
    enc = Encoder(backend, settings.state_dir)
    enc.load()
    assert (settings.state_dir / "memory.json").is_file()
    assert Encoder(FakeBackend(), settings.state_dir).estimate_gb(frozenset()) == 1.0


def test_idle_unload(encoder):
    assert not encoder.idle_due(60)
    encoder.load()
    now = encoder.last_used
    assert not encoder.idle_due(60, now + 30) and encoder.idle_due(60, now + 61)
    assert not encoder.idle_due(0, now + 10_000)                        # 0 = never


def test_errors(client, hub):
    r = client.post("/v1/embed", json={"inputs": [{"image": "output:nope"}]})
    assert r.status_code == 404 and r.json()["code"] == "output_not_found" and r.json()["fix"]
    hub.add("aud", "audio", wav(1))
    r = client.post("/v1/embed", json={"inputs": [{"image": "aud"}]})
    assert r.status_code == 422 and r.json()["code"] == "wrong_kind" and "audio" in r.json()["fix"]
    hub.add("bad", "image", b"not a picture")
    r = client.post("/v1/embed", json={"inputs": [{"image": "bad"}]})
    assert r.status_code == 415 and r.json()["code"] == "bad_media"
    assert client.post("/v1/embed", json={"inputs": [{"text": "a", "image": "x"}]}).status_code == 422
    assert client.post("/v1/embed", json={"inputs": [{}]}).status_code == 422
    assert client.post("/v1/embed", json={"inputs": []}).status_code == 422
    r = client.post("/v1/embed", json={"inputs": [{"text": "x"}] * 257})
    assert r.status_code == 413 and r.json()["code"] == "too_many"


def test_registers_the_model_and_reports_info(client, hub):
    info = client.get("/v1/info").json()                               # (registration ran at startup)
    assert hub.models and hub.models[0]["path"] == "embed/embeddinggemma-2"
    assert hub.models[0]["source"] == {"type": "huggingface", "repo": "google/embeddinggemma-2",
                                       "revision": hub.models[0]["source"]["revision"]}
    assert info["dims"] == [768, 512, 256, 128] and info["weights"] is True and info["loaded"] is None
    schema = client.get("/openapi.json").json()["components"]["schemas"]["Input"]["properties"]["image"]
    assert schema["format"] == "aihub-file" and schema["x-kind"] == "image"
