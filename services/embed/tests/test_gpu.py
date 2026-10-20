"""The real model (run with `pytest -m gpu`; needs the weights): text finds the matching picture, each kind
embeds, and unloading gives the memory back."""

from __future__ import annotations

import functools
import os
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

from embed.encoder import Encoder, GemmaBackend, footprint_bytes, prompt
from embed.media import audio, video
from embed.worker import WorkerBackend
from tests.conftest import mp4, wav

MODEL = Path(os.environ.get("EMBED_MODEL_DIR") or Path(__file__).resolve().parents[3] / "data/models/embed/embeddinggemma-2")
pytestmark = [pytest.mark.gpu,
              pytest.mark.skipif(not (MODEL / "model.safetensors").is_file(), reason=f"no weights in {MODEL}")]
BATCH = {"text": 8, "image": 4, "audio": 1, "video": 1}


def shape(color: str, kind: str) -> Image.Image:
    im = Image.new("RGB", (384, 384), "white")
    d = ImageDraw.Draw(im)
    if kind == "circle":
        d.ellipse((60, 60, 324, 324), fill=color)
    elif kind == "square":
        d.rectangle((60, 60, 324, 324), fill=color)
    else:
        d.polygon([(192, 40), (350, 340), (34, 340)], fill=color)
    return im


@pytest.fixture(scope="module")
def enc(tmp_path_factory):
    e = Encoder(WorkerBackend(functools.partial(GemmaBackend, MODEL)), tmp_path_factory.mktemp("state"))
    yield e
    e.unload()


def test_text_ranks_the_matching_image_first(enc):
    shapes = [("red", "circle"), ("blue", "square"), ("green", "triangle")]
    images = enc.embed([("image", shape(c, k)) for c, k in shapes], 768, BATCH)
    for i, (c, k) in enumerate(shapes):
        q = enc.embed([("text", prompt(f"a {c} {k}", "query"))], 768, BATCH)[0]
        assert int(np.argmax(images @ q)) == i, (c, k, images @ q)
    assert enc.parts == {"vision"}


def test_each_kind_and_matryoshka(enc, tmp_path):
    clip = mp4(tmp_path, 3)
    items = [("text", prompt("hello", "document")), ("audio", audio(wav(2), 320, tmp_path).value),
             ("video", video(clip, 32, tmp_path).value)]
    v = enc.embed(items, 256, BATCH)
    assert v.shape == (3, 256) and np.allclose(np.linalg.norm(v, axis=1), 1, atol=1e-3)
    assert not np.isnan(v).any()
    assert enc.parts == {"vision", "audio"} and enc.backend.dtype in ("bfloat16", "float32")


def test_unload_frees_memory(enc):
    enc.load()
    loaded = enc.backend.footprint_bytes()
    proc = enc.backend.proc
    assert loaded > 1e9 and enc.backend.dtype in ("bfloat16", "float32")
    assert enc.unload()
    assert not proc.is_alive() and footprint_bytes() < 1e9       # the worker is gone; this process never had torch
    assert not enc.loaded
