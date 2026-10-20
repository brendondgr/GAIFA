"""Decision models, one small adapter each (`decide/models/<id>.py`).

An adapter is a class with:
- `ID`, `NAME`, `REPO`, `REVISION` (the one revision whose code was read), `FOLDER` (under data/models/decide/),
  `LICENSE`, `PARAMS` (a short size string) and `INPUTS` (text, image, video);
- `check(folder) -> list[str]`: why the files in `folder` must not be loaded (an unread revision, changed code,
  missing weights); empty when they may;
- `load(folder, device, batch_size, verify)`, `unload()`, and `device` / `dtype` once loaded;
- `ask(input, questions, images, videos) -> {id: answer}`: questions in the mod's own shape
  (`{id, type: yesno | choice | score, question, options?, scale?}`), answers as `{probs, top, p}` (a score adds
  `value`, the expected level, 0 = the first) or `{error, message}` for a question it couldn't answer.

To add a model: write the adapter, add it to ADAPTERS, and record its revision and what its code does in
setup/decide.md.
"""

from __future__ import annotations

from .d3_lite import D3Lite

ADAPTERS: dict[str, type] = {D3Lite.ID: D3Lite}
