"""Decision models, one small adapter per family (`decide/models/<family>.py`), and a card per further model of a family.

An adapter is a class with:
- `ID`, `NAME`, `REPO`, `REVISION` (the one revision whose code was read), `FOLDER` (under data/models/decide/),
  `LICENSE`, `PARAMS` (a short size string) and `INPUTS` (text, image, video);
- `THRESHOLD`: the Auto judge's default cutoff for this model (the lowest "safe" probability that allows a call),
  and `TUNED`: whether the judge's eval measured that cutoff (capability-enablement 7.3); a model it hasn't measured
  is still selectable, shown as "not tuned for this model";
- `check(folder) -> list[str]`: why the files in `folder` must not be loaded (an unread revision, changed code,
  missing weights); empty when they may;
- `load(folder, device, batch_size, verify)`, `unload()`, and `device` / `dtype` once loaded;
- `ask(input, questions, images, videos) -> {id: answer}`: questions in the mod's own shape
  (`{id, type: yesno | choice | score, question, options?, scale?}`), answers as `{probs, top, p}` (a score adds
  `value`, the expected level, 0 = the first) or `{error, message}` for a question it couldn't answer.

Another model of a family that has an adapter needs no Python: a card, `gaifa-decide.toml`, in its folder under
DECIDE_MODELS_DIR (or `decide/models/cards/<id>.toml` shipped with the mod) names the family, the repository, the
revision whose code was read, that revision's code hashes (`[pinned]`) and its threshold. A model of a family with no
adapter is listed as not usable, with the coding-agent prompt to write one. How: README.md, "Adding a decision model".
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from .d3_lite import D3Lite

ADAPTERS: dict[str, type] = {D3Lite.ID: D3Lite}
FAMILIES: dict[str, type] = {"d3": D3Lite}
CARD = "gaifa-decide.toml"
SHIPPED = Path(__file__).resolve().parent / "cards"
WEIGHT_GLOBS = ("*.safetensors", "*.bin", "*.gguf")


def card_class(d: dict[str, Any], families: dict[str, type] = FAMILIES) -> type:
    """A card → its family's adapter with the card's facts (the family's code, this model's pins)."""
    fam = families.get(str(d.get("family", "")))
    if fam is None:
        raise ValueError(f"no adapter for the family {d.get('family')!r} (have: {', '.join(sorted(families))})")
    for key in ("id", "repo", "revision", "weights"):
        if not isinstance(d.get(key), str) or not d[key]:
            raise ValueError(f"a card needs `{key}`")
    attrs = {"ID": d["id"], "NAME": d.get("name") or d["id"], "REPO": d["repo"], "REVISION": d["revision"],
             "FOLDER": d.get("folder") or d["id"], "LICENSE": d.get("license", ""), "PARAMS": d.get("params", ""),
             "WEIGHTS": d["weights"], "THRESHOLD": float(d.get("threshold", 0.35)), "TUNED": bool(d.get("tuned", False)),
             "FAMILY": d["family"], "FROM_CARD": True}
    if "inputs" in d:
        attrs["INPUTS"] = tuple(d["inputs"])
    if "pinned" in d:
        attrs["PINNED"] = {str(k): str(v) for k, v in d["pinned"].items()}
    return type(f"{fam.__name__}_{d['id']}", (fam,), attrs)


def families_of(adapters: dict[str, type]) -> dict[str, type]:
    """Each adapter written in Python (not built from a card) reads its family."""
    return {**FAMILIES, **{c.FAMILY: c for c in adapters.values() if getattr(c, "FAMILY", None) and not getattr(c, "FROM_CARD", False)}}


def with_cards(adapters: dict[str, type], models_dir: Path, families: dict[str, type] | None = None) -> dict[str, type]:
    """The adapters plus every readable card: shipped ones, then those in the model folders (which win)."""
    families = families or families_of(adapters)
    out = dict(adapters)
    files = sorted(SHIPPED.glob("*.toml")) if SHIPPED.is_dir() else []
    if models_dir.is_dir():
        files += sorted(models_dir.glob(f"*/{CARD}"))
    for f in files:
        try:
            cls = card_class(tomllib.loads(f.read_text()), families)
        except (OSError, ValueError, TypeError, tomllib.TOMLDecodeError):
            continue
        out.setdefault(cls.ID, cls) if f.parent == SHIPPED else out.__setitem__(cls.ID, cls)
    return out


def unknown_folders(adapters: dict[str, type], models_dir: Path, families: dict[str, type] | None = None) -> list[dict[str, Any]]:
    """Model folders with weights that no adapter or card claims: shown, not usable, with why and the fix."""
    claimed = {getattr(c, "FOLDER", "") for c in adapters.values()}
    out = []
    if not models_dir.is_dir():
        return out
    for d in sorted(models_dir.iterdir()):
        if not d.is_dir() or d.name in claimed or d.name.startswith("."):
            continue
        if not any(next(d.glob(g), None) for g in WEIGHT_GLOBS):
            continue
        why = "no card: GAIFA doesn't know which family's adapter reads it"
        if (d / CARD).is_file():
            try:
                card_class(tomllib.loads((d / CARD).read_text()), families or families_of(adapters))
            except (ValueError, TypeError, tomllib.TOMLDecodeError) as e:
                why = f"its card can't be used: {e}"
        out.append({"id": d.name, "name": d.name, "path": f"decide/{d.name}", "usable": False, "problems": [why],
                    "fix": "write an adapter or a card for it: gaifa setup --prompt decide gives your coding agent "
                           "the task (services/decide/README.md, Adding a decision model)"})
    return out
