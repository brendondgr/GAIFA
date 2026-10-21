"""A fake decision model for the tests: deterministic answers from words in the input, no torch.

yes/no: "yes" when the input contains the question's `yes_if` word (tests put it in the question as
`[yes_if: word]`), else 0.1. choice: the first option named in the input gets 0.8. score: the level named in
the input gets 0.7. A question containing "[too long]" is answered `max_length_exceeded`; an input containing
"[gpu error]" raises the RuntimeError a GPU library would.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


class FakeModel:
    ID = "fake"
    NAME = "Fake decision model"
    REPO = "test/fake"
    REVISION = "0" * 40
    FOLDER = "fake"
    LICENSE = "none"
    PARAMS = "0"
    INPUTS = ("text", "image")
    WEIGHTS = "weights.bin"
    calls: list[dict[str, Any]] = []        # every ask, shared, for the tests to inspect
    loads: list[str] = []

    def __init__(self) -> None:
        self.device = "cpu"
        self.dtype = "float32"
        self.loaded = False

    @classmethod
    def check(cls, folder: Path) -> list[str]:
        if not (folder / cls.WEIGHTS).is_file():
            return [f"no weights in {folder}"]
        rev = folder / "revision"
        if rev.is_file() and rev.read_text().strip() != cls.REVISION:
            return [f"revision {rev.read_text().strip()[:12]} was downloaded; only {cls.REVISION[:12]} is allowed"]
        return []

    def load(self, folder: Path, device: str = "auto", batch_size: int = 8, verify: str = "full") -> None:
        problems = self.check(folder)
        if problems:
            raise PermissionError("; ".join(problems))
        self.loaded = True
        self.batch_size = batch_size
        FakeModel.loads.append(str(folder))

    def unload(self) -> None:
        self.loaded = False

    def ask(self, state: Any, questions: list[dict[str, Any]], images: list[bytes] | None = None,
            videos: list[tuple[str, bytes]] | None = None) -> dict[str, Any]:
        assert self.loaded, "ask while unloaded"
        text = str(state).lower()
        if "[gpu error]" in text:
            raise RuntimeError("miopenStatusUnknownError")
        FakeModel.calls.append({"state": state, "questions": questions, "images": len(images or []),
                                "batches": -(-len(questions) // self.batch_size)})
        out: dict[str, Any] = {}
        for q in questions:
            if "[too long]" in q["question"]:
                out[q["id"]] = {"error": "max_length_exceeded", "message": "over the input limit"}
                continue
            if q["type"] == "yesno":
                m = re.search(r"\[yes_if: (\w+)\]", q["question"])
                yes = 0.97 if m and m.group(1).lower() in text else 0.1
                probs = {"yes": yes, "no": round(1 - yes, 6)}
            else:
                keys = list(q["options"]) if q["type"] == "choice" else list(q["scale"])
                hit = next((k for k in keys if k.lower() in text), keys[0])
                rest = (1 - 0.8) / max(1, len(keys) - 1) if len(keys) > 1 else 0
                probs = {k: (0.8 if k == hit else rest) if len(keys) > 1 else 1.0 for k in keys}
            top = max(probs, key=probs.get)
            a = {"probs": probs, "top": top, "p": probs[top]}
            if q["type"] == "score":
                a["value"] = sum(i * p for i, p in enumerate(probs.values()))
            out[q["id"]] = a
        return out
