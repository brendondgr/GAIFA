"""The text of text and document outputs (plan 24.2): what the agent reads and searches.

`extract(path, kind, subtype) -> Extract` runs a reader from `readers.py` and adds the counts:
`text` (markdown-ish plain text), `pages` (`(start, end)` character offsets, PDFs), `lines`,
`outline` (headings with their offset, line and page), `tokens` (chars / 4, the agent's own
estimate), `scanned` (PDF pages with almost no text), `truncated` (text cut at `MAX_CHARS`)
and `notes` (what the reader couldn't do).

`cached(outputs, oid, main, kind, subtype)` keeps it at `{outputs}/.text/<id>.json` (a
dot-folder, so the index skips it), rebuilt when the main file's mtime or size changes;
`forget(outputs, oid)` removes it (and the page images) when the output is deleted. Blocking:
callers run it in a thread.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from utils.outputs import readers

log = logging.getLogger("gaifa.outputs")

MAX_CHARS = 4_000_000
TEXT_DIR = ".text"
PAGES_DIR = ".previews"  # PDF page images (plan 24.3): `.previews/<id>/`
VERSION = 2  # bump when a reader changes what it writes, so old caches are rebuilt
TEXT_KINDS = ("text", "document")


@dataclass
class Extract:
    text: str = ""
    pages: list[tuple[int, int]] = field(default_factory=list)
    lines: int = 0
    outline: list[dict[str, Any]] = field(default_factory=list)  # {level, title, offset, line, page?}
    tokens: int = 0
    scanned: list[int] = field(default_factory=list)
    truncated: bool = False
    notes: list[str] = field(default_factory=list)

    def page_of(self, offset: int) -> int | None:
        """The 1-based page holding `offset`, for PDFs."""
        for i, (s, e) in enumerate(self.pages):
            if s <= offset < e or (offset == e and i == len(self.pages) - 1):
                return i + 1
        return None

    def line_of(self, offset: int) -> int:
        return self.text.count("\n", 0, max(0, offset)) + 1


def tokens_of(text: str) -> int:
    return (len(text) + 3) // 4


def extract(path: Path, kind: str, subtype: str | None) -> Extract:
    try:
        r = readers.read(path, kind, subtype)
    except Exception as e:  # noqa: BLE001: a broken file gives a note, never an error
        log.info("text of %s: %s", path.name, e)
        r = readers.Read(notes=[f"couldn't read this {subtype or kind} file: {e}"])
    ex = Extract(text=r.text, pages=list(r.pages), scanned=r.scanned, notes=r.notes)
    if len(ex.text) > MAX_CHARS:
        ex.text, ex.truncated = ex.text[:MAX_CHARS], True
        ex.pages = [(s, min(e, MAX_CHARS)) for s, e in ex.pages if s < MAX_CHARS]
        ex.notes.append(f"the text is cut at {MAX_CHARS:,} characters")
    ex.lines = ex.text.count("\n") + (0 if ex.text.endswith("\n") else 1) if ex.text else 0  # a final newline ends the last line
    ex.tokens = tokens_of(ex.text)
    for level, title, off in r.headings:
        if off <= len(ex.text) and title.strip():
            item: dict[str, Any] = {"level": level, "title": title.strip()[:200], "offset": off, "line": ex.line_of(off)}
            if ex.pages:
                item["page"] = ex.page_of(off)
            ex.outline.append(item)
    return ex


# ---- the cache ---------------------------------------------------------------

def cache_file(outputs: Path, oid: str) -> Path:
    return outputs / TEXT_DIR / f"{oid}.json"


def _stamp(p: Path) -> str:
    st = p.stat()
    return f"{st.st_size}:{st.st_mtime_ns}"


def cached(outputs: Path, oid: str, main: str, kind: str, subtype: str | None) -> Extract:
    """The output's text, from `.text/<id>.json` while the main file is unchanged, else read again."""
    src = outputs / main
    stamp = _stamp(src)
    f = cache_file(outputs, oid)
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
        if data.get("v") == VERSION and data.get("stamp") == stamp:
            data["ex"]["pages"] = [tuple(p) for p in data["ex"]["pages"]]
            return Extract(**data["ex"])
    except (OSError, ValueError, KeyError, TypeError):
        pass
    ex = extract(src, kind, subtype)
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_name(f.name + ".part")
        tmp.write_text(json.dumps({"v": VERSION, "stamp": stamp, "ex": asdict(ex)}, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, f)
    except OSError as e:
        log.warning("text cache for %s: %s", oid, e)
    return ex


def forget(outputs: Path, oid: str) -> None:
    """Remove the output's cached text, its screening report (`utils/tools/screen_store.py`) and page images."""
    cache_file(outputs, oid).unlink(missing_ok=True)
    (outputs / TEXT_DIR / f"{oid}.screening.json").unlink(missing_ok=True)
    shutil.rmtree(outputs / PAGES_DIR / oid, ignore_errors=True)
