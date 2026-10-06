"""Move ComfyUI's old output folder into AIHub's outputs/comfy/<date>/ (plan 11.9).

Each file becomes <date>/<HHMMSS>-<slug>.<ext> (the date and time from its modification time),
with a sidecar: the prompt (found in the PNG's embedded graph with the same input detection the
packs use), created_ts, and where it came from. Run: .venv/bin/python scripts/migrate_old_outputs.py <old output dir> [--dry-run]
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from comfy.config import Settings  # noqa: E402
from comfy.convert import to_api  # noqa: E402
from comfy.detect import suggest  # noqa: E402
from comfy.importer import png_text  # noqa: E402
from comfy.nodes import NodeCatalog  # noqa: E402

KINDS = {".png": "image", ".jpg": "image", ".webp": "image", ".mp4": "video", ".webm": "video", ".gif": "video"}


def prompt_of(p: Path, cat: NodeCatalog) -> str | None:
    if p.suffix.lower() != ".png":
        return None
    meta = png_text(p.read_bytes())
    for key in ("prompt", "workflow"):
        try:
            graph = json.loads(meta[key])
            conv = to_api(graph, cat)
            m = suggest(conv, cat).manifest
            t = m["inputs"].get("prompt")
            if t:
                return conv.graph[t["node"]]["inputs"].get(t["field"])
        except Exception:  # noqa: BLE001
            continue
    return None


def main(src: Path, dry: bool) -> None:
    s = Settings.from_env()
    cat = NodeCatalog.load(s.data / "object_info.json")
    moved = 0
    for f in sorted(x for x in src.rglob("*") if x.is_file() and x.suffix.lower() in KINDS):
        ts = f.stat().st_mtime
        when = datetime.fromtimestamp(ts)
        prompt = prompt_of(f, cat)
        stem = re.sub(r"_\d{5}_$", "", f.stem)
        slug = re.sub(r"[^a-z0-9]+", "-", (prompt or stem).lower()).strip("-")[:40].strip("-") or "comfyui"
        dest = s.outputs / f"{when:%Y-%m-%d}" / f"{when:%H%M%S}-{slug}{f.suffix.lower()}"
        n = 2
        while dest.exists():
            dest = dest.with_name(f"{when:%H%M%S}-{slug}-{n}{f.suffix.lower()}")
            n += 1
        side = {"title": (prompt or stem.replace("_", " "))[:80], "kind": KINDS[f.suffix.lower()], "prompt": prompt,
                "created_ts": ts, "source": {"service": "comfy", "migrated_from": str(f)}}
        print(f"{f.relative_to(src)}  ->  {dest.relative_to(s.outputs)}" + (f"   [{prompt[:50]}]" if prompt else ""))
        if not dry:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(f), dest)
            try:
                os.utime(dest, (ts, ts))
            except PermissionError:          # files the container wrote (a mapped uid); created_ts covers it
                pass
            dest.with_name(dest.name + ".json").write_text(json.dumps(side, indent=1))
        moved += 1
    print(f"{'would move' if dry else 'moved'} {moved} file(s)")


if __name__ == "__main__":
    main(Path(sys.argv[1]).expanduser(), "--dry-run" in sys.argv)
