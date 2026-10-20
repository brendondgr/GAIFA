"""The outputs trash: deleting an output moves it to `outputs/.trash/<YYYY-MM-DD>/<path>`,
which the index ignores (it's a dot-folder), and day folders older than 30 days are
purged. To get something back, move it out of the trash to where it was; the watcher
indexes it again.

A file output takes its sidecars and its cached preview along; its cached text and page
images (plan 24.2, 24.3) are deleted. When the same path was
trashed twice on one day, the second goes to `<day>/2/<path>`, and so on.
"""

from __future__ import annotations

import logging
import shutil
from datetime import date, timedelta
from pathlib import Path

from utils.outputs import text
from utils.outputs.describe import output_id
from utils.outputs.entries import day_of
from utils.outputs.media import cache_path

log = logging.getLogger("aihub.outputs")

TRASH = ".trash"
KEEP_DAYS = 30


def _companions(src: Path) -> list[Path]:
    """A file output's sidecars and preview. `<stem>.json` goes only if no other file shares it."""
    out = [src.with_name(src.name + ".json"), cache_path(src)]
    stem = src.with_name(src.stem + ".json")
    if src.suffix.lower() != ".json" and stem.exists():
        others = [p for p in src.parent.iterdir() if p.stem == src.stem and p != src and p.suffix.lower() != ".json"]
        if not others:
            out.append(stem)
    return [p for p in out if p.exists() or p.is_symlink()]


def move(outputs: Path, rel: str, is_dir: bool, today: date | None = None) -> Path:
    """Move `outputs/<rel>` (and its companions) into the trash. Returns where it went."""
    src = outputs / rel
    moving = [src] + ([] if is_dir else _companions(src))
    day = outputs / TRASH / (today or date.today()).isoformat()
    base, n = day, 1
    while any((base / p.relative_to(outputs)).exists() for p in moving):
        n += 1
        base = day / str(n)
    for p in moving:
        dest = base / p.relative_to(outputs)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(p, dest)  # a rename on the same filesystem
    text.forget(outputs, output_id(rel))
    return base / rel


def purge(outputs: Path, keep_days: int = KEEP_DAYS, today: date | None = None) -> int:
    """Delete trash day folders older than `keep_days`. Returns how many went."""
    root = outputs / TRASH
    if not root.is_dir():
        return 0
    cutoff = (today or date.today()) - timedelta(days=keep_days)
    gone = 0
    for d in sorted(root.iterdir()):
        day = day_of(d.name)
        if day is not None and day < cutoff and d.is_dir() and not d.is_symlink():
            shutil.rmtree(d, ignore_errors=True)
            gone += 1
            log.info("outputs trash: purged %s", d.name)
    return gone
