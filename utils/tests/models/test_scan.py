"""3.2: the scanner's rules on a fake data/models/ tree, and adding what it finds."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from utils.registry import adding
from utils.registry.adding import ModelInput
from utils.registry.model import RegistryError
from utils.registry.scan import candidates, slug, unique_id
from utils.tests.models.conftest import Models


def build_tree(m: Models) -> None:
    """One example of every rule in plan 3.2, plus things that must be skipped."""
    # llm/: GGUF grouping (lcpp's catalog rules)
    m.put("llm/Gemma4-26B/Gemma4-26B-A4B-Q4KM.gguf", 100)
    m.put("llm/Gemma4-26B/mmproj-Gemma4-26B-BF16.gguf", 20)
    m.put("llm/Gemma4-26B/mtp-gemma-4-26B.gguf", 10)
    for i in (1, 2, 3):
        m.put(f"llm/Big/Big-Q4_K_M-0000{i}-of-00003.gguf", 50)
    m.put("llm/Two/alpha-Q8_0.gguf", 30)
    m.put("llm/Two/beta-Q4_0.gguf", 30)
    m.put("llm/Two/mmproj-shared.gguf", 5)  # two models in the folder: not attached to either
    m.put("llm/loose-Q8_0.gguf", 40)
    m.put("llm/hfllm/config.json", 2)
    m.put("llm/hfllm/model.safetensors", 60)
    m.put("llm/x.gguf.lock", 1)
    # comfyui/<role>/<file>: one model per file
    m.put("comfyui/diffusion_models/z_image_turbo_fp8.safetensors", 70)
    m.put("comfyui/diffusion_models/wan2.1_t2v_14B_fp8.safetensors", 80)
    m.put("comfyui/unet/SCAIL-2-Q80.gguf", 90)
    m.put("comfyui/checkpoints/sdxl_base.safetensors", 75)
    m.put("comfyui/text_encoders/umt5_xxl_fp8.safetensors", 65)
    m.put("comfyui/vae/wan_2.1_vae.safetensors", 25)
    m.put("comfyui/loras/styles/zit_watercolor.safetensors", 15)
    m.put("comfyui/clip_vision/clip_vision_h.safetensors", 35)
    m.put("comfyui/upscale_models/4x_Remacri.pth", 12)
    m.put("comfyui/configs/v1-inference.yaml", 3)  # not a weight file
    m.put("comfyui/diffusers/qwen-image/model_index.json", 2)
    m.put("comfyui/diffusers/qwen-image/transformer/diffusion_pytorch_model.safetensors", 44)
    # voices/<slug>/voice.json
    m.put("voices/hope/reference.wav", 33)
    m.put("voices/hope/voice.json", json.dumps({"name": "Hope"}).encode())
    m.put("voices/notes/readme.txt", 2)  # no voice.json, no audio
    # hf-cache/hub/models--org--name
    base = "hf-cache/hub/models--Systran--faster-whisper-small"
    m.put(f"{base}/blobs/aaa", 45)
    m.put(f"{base}/blobs/bbb", 4)
    m.put(f"{base}/refs/main", b"rev123")
    snap = m.dir / base / "snapshots/rev123"
    snap.mkdir(parents=True)
    (snap / "model.bin").symlink_to("../../blobs/aaa")
    (snap / "config.json").symlink_to("../../blobs/bbb")
    (m.dir / base / "snapshots/oldrev").mkdir()
    m.put("hf-cache/hub/datasets--org--data/blobs/x", 9)
    m.put("hf-cache/hub/.locks/models--Systran--faster-whisper-small/aaa.lock", 1)
    m.put("hf-cache/xet/chunk.bin", 9)
    m.put("hf-cache/CACHEDIR.TAG", 1)
    # Hugging Face folders and other folders of weights
    m.put("3d/cube3d-v0.5/shape_gpt.safetensors", 55)
    m.put("3d/cube3d-v0.5/shape_tokenizer.safetensors", 11)
    m.put("3d/Qwen3-VL-4B-Instruct/config.json", 2)
    m.put("3d/Qwen3-VL-4B-Instruct/model-00001-of-00002.safetensors", 40)
    m.put("3d/Qwen3-VL-4B-Instruct/model-00002-of-00002.safetensors", 40)
    m.put("3d/Qwen3-VL-4B-Instruct/tokenizer.json", 3)
    m.put("3d/Qwen-Image/transformer/config.json", 2)
    m.put("3d/Qwen-Image/transformer/diffusion_pytorch_model.safetensors", 41)
    m.put("3d/configs-only/config.json", 2)  # a Hugging Face folder with no weights: skipped
    m.put("tts/breeze-tts-2/model.safetensors", 77)
    m.put("tts/breeze-tts-2/preprocessor_config.json", 2)
    m.put("stt/whisper-tiny.bin", 8)
    m.put("root-level.safetensors", 6)
    # always skipped
    m.put("tts/.hidden/x.safetensors", 9)
    m.put("tts/dl.safetensors.part", 9)
    m.put(".cache/huggingface/x.safetensors", 9)


EXPECTED = {
    # path: (kind, name, format, [(file, role)])
    "3d/Qwen-Image/transformer": ("3d", "Qwen-Image/transformer", "hf-dir", [("3d/Qwen-Image/transformer/config.json", "config"), ("3d/Qwen-Image/transformer/diffusion_pytorch_model.safetensors", "weights")]),
    "3d/Qwen3-VL-4B-Instruct": ("3d", "Qwen3-VL-4B-Instruct", "hf-dir", [("3d/Qwen3-VL-4B-Instruct/config.json", "config"), ("3d/Qwen3-VL-4B-Instruct/model-00001-of-00002.safetensors", "weights"), ("3d/Qwen3-VL-4B-Instruct/model-00002-of-00002.safetensors", "weights"), ("3d/Qwen3-VL-4B-Instruct/tokenizer.json", "tokenizer")]),
    "3d/cube3d-v0.5": ("3d", "cube3d-v0.5", "safetensors", [("3d/cube3d-v0.5/shape_gpt.safetensors", "weights"), ("3d/cube3d-v0.5/shape_tokenizer.safetensors", "weights")]),
    "comfyui/checkpoints/sdxl_base.safetensors": ("image", "sdxl_base", "safetensors", None),
    "comfyui/clip_vision/clip_vision_h.safetensors": ("vision", "clip_vision_h", "safetensors", None),
    "comfyui/diffusers/qwen-image": ("image", "qwen-image", "hf-dir", [("comfyui/diffusers/qwen-image/model_index.json", "config"), ("comfyui/diffusers/qwen-image/transformer/diffusion_pytorch_model.safetensors", "weights")]),
    "comfyui/diffusion_models/wan2.1_t2v_14B_fp8.safetensors": ("video", "wan2.1_t2v_14B_fp8", "safetensors", None),
    "comfyui/diffusion_models/z_image_turbo_fp8.safetensors": ("image", "z_image_turbo_fp8", "safetensors", None),
    "comfyui/loras/styles/zit_watercolor.safetensors": ("lora", "zit_watercolor", "safetensors", None),
    "comfyui/text_encoders/umt5_xxl_fp8.safetensors": ("text-encoder", "umt5_xxl_fp8", "safetensors", None),
    "comfyui/unet/SCAIL-2-Q80.gguf": ("video", "SCAIL-2-Q80", "gguf", None),
    "comfyui/upscale_models/4x_Remacri.pth": ("upscale", "4x_Remacri", "pth", None),
    "comfyui/vae/wan_2.1_vae.safetensors": ("vae", "wan_2.1_vae", "safetensors", None),
    "hf-cache/hub/models--Systran--faster-whisper-small": ("stt", "faster-whisper-small", "hf-dir", [
        ("hf-cache/hub/models--Systran--faster-whisper-small/snapshots/rev123/config.json", "config"),
        ("hf-cache/hub/models--Systran--faster-whisper-small/snapshots/rev123/model.bin", "weights"),
        ("hf-cache/hub/models--Systran--faster-whisper-small/refs/main", "ref")]),
    "llm/Big": ("llm", "Big-Q4_K_M", "gguf", [("llm/Big/Big-Q4_K_M-00001-of-00003.gguf", "model"), ("llm/Big/Big-Q4_K_M-00002-of-00003.gguf", "split"), ("llm/Big/Big-Q4_K_M-00003-of-00003.gguf", "split")]),
    "llm/Gemma4-26B": ("llm", "Gemma4-26B-A4B-Q4KM", "gguf", [("llm/Gemma4-26B/Gemma4-26B-A4B-Q4KM.gguf", "model"), ("llm/Gemma4-26B/mmproj-Gemma4-26B-BF16.gguf", "mmproj"), ("llm/Gemma4-26B/mtp-gemma-4-26B.gguf", "draft")]),
    "llm/Two/alpha-Q8_0.gguf": ("llm", "alpha-Q8_0", "gguf", [("llm/Two/alpha-Q8_0.gguf", "model")]),
    "llm/Two/beta-Q4_0.gguf": ("llm", "beta-Q4_0", "gguf", [("llm/Two/beta-Q4_0.gguf", "model")]),
    "llm/hfllm": ("llm", "hfllm", "hf-dir", [("llm/hfllm/config.json", "config"), ("llm/hfllm/model.safetensors", "weights")]),
    "llm/loose-Q8_0.gguf": ("llm", "loose-Q8_0", "gguf", [("llm/loose-Q8_0.gguf", "model")]),
    "root-level.safetensors": ("other", "root-level", "safetensors", None),
    "stt/whisper-tiny.bin": ("stt", "whisper-tiny", "bin", None),
    "tts/breeze-tts-2": ("tts", "breeze-tts-2", "hf-dir", [("tts/breeze-tts-2/model.safetensors", "weights"), ("tts/breeze-tts-2/preprocessor_config.json", "config")]),
    "voices/hope": ("voice", "Hope", "wav", [("voices/hope/reference.wav", "reference"), ("voices/hope/voice.json", "meta")]),
}


def test_scanner_finds_exactly_the_expected_models(models):
    build_tree(models)
    found = {c.path: c for c in candidates(models.dir)}
    assert sorted(found) == sorted(EXPECTED)
    for path, (kind, name, fmt, files) in EXPECTED.items():
        c = found[path]
        assert (c.kind, c.name, c.format) == (kind, name, fmt), path
        assert [(f["path"], f["role"]) for f in c.files] == (files or [(path, "weights")]), path
    whisper = found["hf-cache/hub/models--Systran--faster-whisper-small"]
    assert whisper.source == {"type": "huggingface", "repo": "Systran/faster-whisper-small", "revision": "rev123"}
    assert whisper.size_bytes == 45 + 4 + 6  # sizes through the snapshot links
    assert found["voices/hope"].source == {"type": "created"}
    assert found["llm/Big"].size_bytes == 150


async def test_scan_route_then_add_everything(root, client):
    m = Models(root)
    build_tree(m)
    r = await client.post("/api/models/scan")
    assert r.status_code == 200
    disc = r.json()["discovered"]
    assert sorted(d["path"] for d in disc) == sorted(EXPECTED)
    ids = [d["suggested_id"] for d in disc]
    assert len(set(ids)) == len(ids) and "gemma4-26b-a4b-q4km" in ids
    for d in disc:
        r = await client.post("/api/models", json={"path": d["path"], "name": d["suggested_name"], "kind": d["suggested_kind"], "source": {"type": "local"}})
        assert r.status_code == 201, (d["path"], r.text)
    assert (await client.post("/api/models/scan")).json()["discovered"] == []
    listed = (await client.get("/api/models")).json()
    assert listed["totals"]["count"] == len(EXPECTED)
    w = (await client.get("/api/models/faster-whisper-small")).json()
    assert w["source"]["type"] == "huggingface" and w["status"] == "unverified"  # the scanner's source beats the UI's bare "local"
    g = (await client.get("/api/models/gemma4-26b-a4b-q4km")).json()
    assert [f["role"] for f in g["files"]] == ["model", "mmproj", "draft"] and g["format"] == "gguf" and g["size_bytes"] == 130
    stored = m.read()["models"]["gemma4-26b-a4b-q4km"]
    assert stored["files"][0] == {"path": "llm/Gemma4-26B/Gemma4-26B-A4B-Q4KM.gguf", "role": "model", "size_bytes": 100, "sha256": None, "verified_at": None}


async def test_scan_offers_new_files_next_to_registered_ones(root, client):
    m = Models(root)
    m.put("llm/G/g-Q4.gguf", 10)
    assert (await client.post("/api/models", json={"path": "llm/G", "name": "G", "kind": "llm"})).status_code == 201
    m.put("llm/G/g-Q8.gguf", 20)  # a second quant in the same folder
    m.put("tts/x/config.json", 2)
    m.put("tts/x/model.safetensors", 5)
    assert (await client.post("/api/models", json={"path": "tts/x", "name": "X", "kind": "tts"})).status_code == 201
    m.put("tts/x/extra.safetensors", 5)  # inside a registered HF folder: part of it, not a new model
    disc = (await client.post("/api/models/scan")).json()["discovered"]
    assert [d["path"] for d in disc] == ["llm/G/g-Q8.gguf"]


async def test_add_errors(root, client):
    m = Models(root)
    m.put("vae/a.safetensors", 4)
    ok = {"path": "vae/a.safetensors", "name": "A", "kind": "vae"}
    r = await client.post("/api/models", json={**ok, "path": "vae/missing.safetensors"})
    assert r.status_code == 422 and "doesn't exist" in r.json()["detail"]
    r = await client.post("/api/models", json={**ok, "path": "../outside"})
    assert r.status_code == 422 and r.json()["code"] == "invalid_request"
    r = await client.post("/api/models", json={**ok, "kind": "nope"})
    assert r.status_code == 422
    r = await client.post("/api/models", json={**ok, "id": "Bad Id"})
    assert r.status_code == 422 and "id:" in r.json()["detail"]
    r = await client.post("/api/models", json=ok)
    assert r.status_code == 201 and r.json()["id"] == "a" and r.json()["source"] is None
    r = await client.post("/api/models", json={**ok, "name": "Again"})
    assert (r.status_code, r.json()["code"]) == (409, "model_exists") and "already registered as a" in r.json()["detail"]
    m.put("vae/b.safetensors", 4)
    r = await client.post("/api/models", json={"path": "vae/b.safetensors", "name": "A", "kind": "vae"})
    assert r.json()["id"] == "a-2"  # same name, no id given: a free id is picked
    m.put("vae/c.safetensors", 4)
    r = await client.post("/api/models", json={"path": "vae/c.safetensors", "name": "C", "kind": "vae", "id": "a"})
    assert (r.status_code, r.json()["code"]) == (409, "model_exists")
    (m.dir / "empty").mkdir()
    r = await client.post("/api/models", json={"path": "empty", "name": "E", "kind": "other"})
    assert r.status_code == 422 and "no model files" in r.json()["detail"]


async def test_a_mod_registers_its_download_with_explicit_files(root, client):
    m = Models(root)
    m.put("llm/dl/model.gguf", 10)
    m.put("llm/dl/mmproj-model.gguf", 3)
    body = {"path": "llm/dl", "name": "Downloaded", "kind": "llm", "id": "dl-model", "services": ["lcpp"],
            "source": {"type": "huggingface", "repo": "org/repo", "revision": "abc"},
            "files": [{"path": "llm/dl/model.gguf", "role": "model", "sha256": "A" * 64}, {"path": "llm/dl/mmproj-model.gguf", "role": "mmproj"}]}
    r = await client.post("/api/models", json=body)
    assert r.status_code == 201
    v = r.json()
    assert v["services"] == ["lcpp"] and v["files"][0]["sha256"] == "a" * 64 and v["status"] == "unverified"
    assert v["source"] == {"type": "huggingface", "repo": "org/repo", "revision": "abc"}


def test_slug_and_unique_id():
    assert slug("Gemma 4 26B (Q4_K_M)") == "gemma-4-26b-q4-k-m"
    assert slug("wan2.1_t2v") == "wan2.1-t2v" and slug("...") == "model" and len(slug("x" * 100)) == 64
    assert unique_id("A", {"a", "a-2"}) == "a-3"


def test_scanner_survives_odd_trees(models):
    (models.dir / "llm").mkdir()
    (models.dir / "llm/loop").symlink_to(models.dir / "llm")  # a symlink loop must not hang the walk
    (models.dir / "broken.gguf").symlink_to(models.dir / "nowhere.gguf")
    unreadable = models.dir / "tts/locked"
    unreadable.mkdir(parents=True)
    models.put("tts/locked/m.safetensors")
    unreadable.chmod(0)
    try:
        found = candidates(models.dir)
    finally:
        unreadable.chmod(0o755)
    assert all(not c.path.startswith("broken") for c in found)
