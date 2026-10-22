"""vllm-sr/d3-lite: vLLM Semantic Router's Decision 3.0, 0.85B (Qwen3.5-0.8B + a 0.10B vision encoder),
Apache-2.0, BF16. Loaded with Transformers `AutoModel.from_pretrained(folder, trust_remote_code=True)`, which runs
the repository's own code (`modeling_d3.py` → `d3_runtime.py`, `d3_format.py`, `d3_fast.py`). That code was read
at REVISION before it was allowed (setup/decide.md, "The remote code"), so `check` refuses any other revision and
any changed or added code file.
"""

from __future__ import annotations

import base64
import gc
import hashlib
import io
from pathlib import Path
from typing import Any

from .. import device as devices

ANSWER_ERRORS = ("invalid_question", "max_length_exceeded", "invalid_model_output")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(16 << 20), b""):
            h.update(block)
    return h.hexdigest()


def to_d3(q: dict[str, Any]) -> dict[str, Any]:
    """One question in the mod's shape → d3's System One shape (yesno is d3's `noul`)."""
    if q["type"] == "yesno":
        return {"type": "noul", "instructions": q["question"]}
    if q["type"] == "choice":
        opts = q["options"]
        criteria = dict(opts) if isinstance(opts, dict) else {o: None for o in opts}
        return {"type": "choice", "instructions": q["question"], "criteria": criteria}
    return {"type": "score", "instructions": q["question"], "criteria": list(q["scale"])}


def from_d3(q: dict[str, Any], a: dict[str, Any]) -> dict[str, Any]:
    """d3's answer → `{probs, top, p}` (a score adds `value`: the expected level, 0 = the first)."""
    if "error" in a:
        return {"error": a["error"], "message": a.get("message", "")}
    if q["type"] == "yesno":
        yes = float(a["noul"])
        probs = {"yes": yes, "no": 1.0 - yes}
    elif q["type"] == "choice":
        probs = {k: float(v) for k, v in a["probabilities"].items()}
    else:
        scale = list(q["scale"])
        probs = {scale[int(k)]: float(v) for k, v in a["probabilities"].items()}
    top = max(probs, key=probs.get)
    out = {"probs": {k: round(v, 6) for k, v in probs.items()}, "top": top, "p": round(probs[top], 6)}
    if q["type"] == "score":
        out["value"] = round(float(a["score"]), 4)
    return out


class D3Lite:
    ID = "d3-lite"
    NAME = "d3-lite (Decision 3.0)"
    REPO = "vllm-sr/d3-lite"
    REVISION = "03560c26f5199c3c04129a2ccb38960c913635e0"     # 2026-10-17; read 2026-10-20
    FOLDER = "d3-lite"
    LICENSE = "apache-2.0"
    PARAMS = "0.85B"
    INPUTS = ("text", "image", "video")
    WEIGHTS = "model-00001-of-00001.safetensors"
    # Every code file at REVISION (the d3 runtime imports d3_fast.py and d3_kernels.py by path from the folder),
    # and the manifest the runtime checks the weights, tokenizer and configs against (verify = full | fast).
    PINNED = {
        "MODEL_MANIFEST.json": "31f0ff94ff26619c0a063ccac803edcfe34c56c92e5c9c50b703b62893f125dd",
        "modeling_d3.py": "f8f8db23ff58f1a990ffa24977d744a50e1b4446d02a64c22070967705b6dbef",
        "d3_runtime.py": "adf7f7aa085674b5682e492d8b2e3cc4f11c67b0d153515c742e907e9b550917",
        "d3_format.py": "3badfbc70561bb3f5b8ec16a11d2c455b96ddb32caace0a8a54ca102eae1f3fa",
        "d3_fast.py": "68a1fb9a2c3bde9ac2763bf504decae592ca12722698fbde1b39a31262955535",
        "d3_kernels.py": "8f7534ca1e1846ebf7c4c73058002f3be4dbf0d5d426f0815150ae0cbe7677bd",
        "pipeline_d3.py": "4f9297c7c74e596e9b67df91a1e6823cfada48bf781336f141974ff6a2f1038e",
        "d3_server.py": "766a20a69101e36ab0535a1ec683379db422380a83091f0eccd7e82edb6a02de",
        "d3_engine.py": "086238942762df45047a32cd9a8e2bedd9b63167eb40be260c776de567979f53",
    }

    def __init__(self) -> None:
        self.model: Any = None
        self.device = "cpu"
        self.dtype = "bfloat16"

    @classmethod
    def check(cls, folder: Path) -> list[str]:
        """Why this folder must not be loaded; empty when it holds REVISION's files unchanged."""
        if not (folder / cls.WEIGHTS).is_file():
            return [f"no weights in {folder} (run services/decide/install.sh)"]
        problems = []
        meta = folder / ".cache" / "huggingface" / "download" / "modeling_d3.py.metadata"
        if meta.is_file():            # hf download --local-dir records the commit it fetched
            got = (meta.read_text().splitlines() or [""])[0].strip()
            if got != cls.REVISION:
                problems.append(f"revision {got[:12]} was downloaded; only {cls.REVISION[:12]} was read and is allowed")
        for name, want in cls.PINNED.items():
            p = folder / name
            if not p.is_file():
                problems.append(f"{name} is missing")
            elif sha256(p) != want:
                problems.append(f"{name} differs from revision {cls.REVISION[:12]}, whose code was read")
        extra = sorted(p.name for p in folder.glob("*.py") if p.name not in cls.PINNED)
        problems += [f"{n}: a code file that revision {cls.REVISION[:12]} doesn't have" for n in extra]
        return problems

    def load(self, folder: Path, device: str = "auto", batch_size: int = 8, verify: str = "full") -> None:
        problems = self.check(folder)
        if problems:
            raise PermissionError("; ".join(problems))
        if verify not in ("full", "fast"):
            raise ValueError("verify must be full or fast")
        import torch
        from transformers import AutoModel

        dev = devices.device(device)       # plan 39.3: auto → AIHUB_DEVICE (the variant), else the first torch reaches
        if dev != "cpu" and not devices.available(dev):
            if device not in ("", "auto"):
                raise RuntimeError(f"DECIDE_DEVICE={device} but torch can't reach {dev}")
            dev = "cpu"
        # The Gated DeltaNet layers' short convolution went to MIOpen, which times its algorithms for every new
        # input length. On 2026-10-21 a worker's timings all read 0, so every length not timed before failed
        # ("No suitable algorithm"). PyTorch's own depthwise kernel does the same sum with no search (d3 already
        # runs its vision patch embedding without MIOpen, for the same search). This process runs only d3.
        torch.backends.cudnn.enabled = False
        self.model = AutoModel.from_pretrained(str(folder), trust_remote_code=True, local_files_only=True,
                                               device=f"{dev}:0" if dev in ("cuda", "xpu") else dev, batch_size=batch_size,
                                               verify=verify)
        self.device = dev
        # The first question after a load takes about 2 s (kernel selection); pay it here, not on a caller's call.
        self.model.system_one(state="warm-up", questions={"q": {"type": "noul"}})

    def unload(self) -> None:
        if self.model is None:
            return
        self.model = None
        gc.collect()
        if self.device and self.device != "cpu":
            devices.empty_cache(self.device)

    def ask(self, state: Any, questions: list[dict[str, Any]], images: list[bytes] | None = None,
            videos: list[tuple[str, bytes]] | None = None) -> dict[str, Any]:
        """One forward pass per question, `batch_size` questions at a time; every question sees the images and
        videos. Images are encoded files; videos are (mime type, bytes)."""
        from PIL import Image

        pics = [Image.open(io.BytesIO(b)).convert("RGB") for b in images or []]
        clips = [f"data:{mime};base64,{base64.b64encode(b).decode()}" for mime, b in videos or []]
        res = self.model.system_one(state=state, questions={q["id"]: to_d3(q) for q in questions},
                                    images=pics or None, videos=clips or None)
        return {q["id"]: from_d3(q, res["answers"][q["id"]]) for q in questions}
