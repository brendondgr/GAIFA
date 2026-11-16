"""Measure embed models on this machine (capability-enablement 7.3): load time, texts a second, memory, and a small
retrieval score on GAIFA's own fixture set (evals/fixture.json): recall@1 and MRR over 24 questions.

Run from services/embed with the mod's venv:  .venv/bin/python -m evals.measure <models-dir> <model>… [--cpu]
The results are printed as JSON lines; docs/embed-models.md keeps them.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

from embed import models
from embed.encoder import Encoder, GemmaBackend, footprint_bytes

HERE = Path(__file__).resolve().parent


def backend(info: models.ModelInfo, device: str):
    return GemmaBackend(info.folder, device) if info.backend == "gemma" else models.TextBackend(info, device)


def measure(info: models.ModelInfo, device: str) -> dict:
    fx = json.loads((HERE / "fixture.json").read_text())
    ids = list(fx["docs"])
    enc = Encoder(backend(info, device), None, info)
    t0 = time.perf_counter()
    enc.load()
    load_s = time.perf_counter() - t0
    enc.embed([("text", enc.prompt("warm up", "query"))], None, {"text": 1})
    texts = [enc.prompt(f"a short sentence about thing number {i}", "document") for i in range(40)]
    t1 = time.perf_counter()
    enc.embed([("text", t) for t in texts], None, {"text": 32})
    rate = 40 / (time.perf_counter() - t1)
    D = enc.embed([("text", enc.prompt(fx["docs"][i], "document")) for i in ids], None, {"text": 32})
    Q = enc.embed([("text", enc.prompt(q, "query")) for q, _ in fx["queries"]], None, {"text": 32})
    ranks = []
    for qi, (_, want) in enumerate(fx["queries"]):
        order = [ids[j] for j in np.argsort(-(D @ Q[qi]))]
        ranks.append(order.index(want) + 1)
    gb = round(footprint_bytes() / 1e9, 2)
    enc.unload()
    return {"model": info.id, "name": info.name, "device": enc.backend.device, "dtype": enc.backend.dtype,
            "dim": info.dim, "load_s": round(load_s, 2), "texts_per_s": round(rate, 1), "process_gb": gb,
            "recall_at_1": round(sum(r == 1 for r in ranks) / len(ranks), 3),
            "mrr": round(float(np.mean([1 / r for r in ranks])), 3), "queries": len(ranks)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("models_dir", type=Path)
    ap.add_argument("models", nargs="+")
    ap.add_argument("--cpu", action="store_true")
    a = ap.parse_args()
    for m in a.models:
        print(json.dumps(measure(models.read(a.models_dir / m), "cpu" if a.cpu else "auto")), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
