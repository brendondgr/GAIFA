"""Text into overlapping chunks that keep their place (plan 28.2): about 800 tokens with 100 of overlap, cut at
a paragraph, line, sentence or word end near the limit; each chunk knows its character offset, page and line.
Tokens are estimated as characters / 4, the hub's own estimate (`/api/outputs/{id}/text` `tokens`)."""

from __future__ import annotations

import re
from dataclasses import dataclass

CHARS_PER_TOKEN = 4
SIZE = 800 * CHARS_PER_TOKEN
OVERLAP = 100 * CHARS_PER_TOKEN
BREAKS = ("\n\n", "\n", ". ", "? ", "! ", "; ", ", ", " ")


@dataclass
class TextChunk:
    text: str
    offset: int
    page: int | None            # 1-based, for texts with pages (PDFs)
    line: int                   # 1-based line of the chunk's first character


def _cut(text: str, start: int, size: int) -> int:
    """Where a chunk starting at `start` ends: at the latest break in its last fifth, else at `size`."""
    end = start + size
    if end >= len(text):
        return len(text)
    floor = start + int(size * 0.8)
    for b in BREAKS:
        i = text.rfind(b, floor, end)
        if i >= 0:
            return i + len(b)
    return end


def chunk(text: str, page_starts: list[int] | None = None, size: int = SIZE, overlap: int = OVERLAP) -> list[TextChunk]:
    """`page_starts`: each page's first character offset, ascending (from the text route's `pages=N` windows).
    With pages, no chunk crosses a page's end, so every line a search finds in a chunk is on that chunk's page."""
    if page_starts:
        bounds = [*page_starts, len(text)]
        paged: list[TextChunk] = []
        for n, (a, b) in enumerate(zip(bounds, bounds[1:]), 1):
            first = text.count("\n", 0, a) + 1
            paged += [TextChunk(c.text, a + c.offset, n, first + c.line - 1) for c in chunk(text[a:b], None, size, overlap)]
        return paged
    out: list[TextChunk] = []
    start, line, counted = 0, 1, 0
    n = len(text)
    while start < n:
        end = _cut(text, start, size)
        piece = text[start:end]
        if piece.strip():
            line += text.count("\n", counted, start)
            counted = start
            out.append(TextChunk(piece, start, None, line))
        if end >= n:
            break
        nxt = max(end - overlap, start + 1)
        space = text.find(" ", nxt, end)                 # start the overlap on a word
        start = space + 1 if 0 <= space < end - 1 else nxt
    return out


def snippet(text: str, limit: int = 300) -> str:
    s = re.sub(r"\s+", " ", text).strip()
    return s if len(s) <= limit else s[:limit].rsplit(" ", 1)[0] + " …"
