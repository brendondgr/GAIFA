"""Reading and searching an output's text, and PDF page images (plan 24.3). Blocking: callers
run these in a thread.

- `window(ex, offset, limit, pages)`: a slice of the text; `pages` (`"3"` or `"3-5"`) starts at
  that page and stops at the range's end; `next_offset` continues through the document.
- `search(ex, q, limit)`: words (all in one line, else in one paragraph), a `"quoted phrase"`
  (exact, any case, any whitespace between its words), or a `/regex/` (`/regex/i` ignores case)
  run in a separate Python with a 1 s timeout, so a runaway pattern can't stall the hub.
- `page_png(src, n, width, out)`: page `n` of a PDF rendered by `pypdfium2`, cached at `out`.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from utils.outputs.index import OutputError
from utils.outputs.readers import _PDFIUM
from utils.outputs.text import Extract

LIMIT = 12_000
MAX_LIMIT = 48_000
SEARCH_LIMIT = 20
REGEX_TIMEOUT_S = 1.0
MAX_MATCHES = 5000
PAGE_WIDTH = 1200

_REGEX_CHILD = r"""
import json, re, sys
a = json.loads(sys.stdin.read())
try:
    rx = re.compile(a["pattern"], re.I if a["i"] else 0)
except re.error as e:
    print(json.dumps({"error": str(e)})); sys.exit()
out = []
for m in rx.finditer(a["text"]):
    out.append(m.start())
    if len(out) >= a["max"]:
        break
print(json.dumps({"starts": out}))
"""


def no_page(detail: str) -> OutputError:
    return OutputError(404, "no_page", detail)


def page_range(spec: str, ex: Extract) -> tuple[int, int]:
    m = re.fullmatch(r"\s*(\d+)\s*(?:-\s*(\d+)\s*)?", spec or "")
    if not m:
        raise OutputError(422, "invalid_request", f'pages: "{spec}" is not a page or a range like 3-5')
    a, b = int(m[1]), int(m[2] or m[1])
    if not ex.pages:
        raise no_page("This output has no pages; read it by offset")
    if a < 1 or b < a or b > len(ex.pages):
        raise no_page(f"No page {spec}: the document has {len(ex.pages)} pages")
    return a, b


def window(ex: Extract, offset: int = 0, limit: int = LIMIT, pages: str | None = None) -> dict[str, Any]:
    total = len(ex.text)
    limit = max(1, min(limit, MAX_LIMIT))
    if pages:
        a, b = page_range(pages, ex)
        start, stop = ex.pages[a - 1][0], ex.pages[b - 1][1]
    else:
        start, stop = min(max(0, offset), total), total
    end = min(stop, start + limit)
    if end < stop:  # cut at a line end when one is near
        nl = ex.text.rfind("\n", start + int(limit * 0.8), end)
        if nl > start:
            end = nl + 1
    return {
        "text": ex.text[start:end], "offset": start, "next_offset": end if end < total else None,
        "total_chars": total, "tokens": ex.tokens, "pages": len(ex.pages), "lines": ex.lines,
        "page_of_offset": ex.page_of(start), "outline": ex.outline, "scanned": ex.scanned,
        "truncated": ex.truncated, "notes": ex.notes,
    }


# ---- search ----------------------------------------------------------------------

def _regex_starts(text: str, pattern: str, ignore_case: bool) -> list[int]:
    try:
        r = subprocess.run([sys.executable, "-I", "-S", "-c", _REGEX_CHILD], timeout=REGEX_TIMEOUT_S, capture_output=True,
                           input=json.dumps({"pattern": pattern, "i": ignore_case, "text": text, "max": MAX_MATCHES}).encode(),
                           check=False, env={"PATH": os.environ.get("PATH", "")})
    except subprocess.TimeoutExpired:
        raise OutputError(422, "search_timeout", f"/{pattern}/ took longer than {REGEX_TIMEOUT_S:g} s; try words or a simpler pattern") from None
    try:
        out = json.loads(r.stdout)
    except ValueError:
        raise OutputError(500, "hub_error", f"regex search failed: {r.stderr.decode(errors='replace')[-300:]}") from None
    if "error" in out:
        raise OutputError(422, "invalid_request", f"/{pattern}/ is not a valid pattern: {out['error']}")
    return out["starts"]


def _starts(ex: Extract, q: str) -> list[int]:
    text = ex.text
    if m := re.fullmatch(r"/(.+)/(i?)", q, re.S):
        return _regex_starts(text, m[1], bool(m[2]))
    if len(q) >= 2 and q[0] == q[-1] == '"':
        words = q[1:-1].split()
        if not words:
            return []
        rx = re.compile(r"\s+".join(map(re.escape, words)), re.I)
        return [m.start() for m in rx.finditer(text)]
    words = q.lower().split()
    if not words:
        return []
    lines = text.split("\n")
    pos, line_at = 0, []
    for line in lines:
        line_at.append(pos)
        pos += len(line) + 1
    low = [x.lower() for x in lines]
    hit_lines: list[int] = [i for i, x in enumerate(low) if all(w in x for w in words)]
    hit = set(hit_lines)
    # paragraphs (runs of non-blank lines) holding every word, though no single line does
    i = 0
    while i < len(low):
        if not low[i].strip():
            i += 1
            continue
        j = i
        while j < len(low) and low[j].strip():
            j += 1
        if not hit.intersection(range(i, j)) and all(w in "\n".join(low[i:j]) for w in words):
            hit_lines.append(next(k for k in range(i, j) if any(w in low[k] for w in words)))
        i = j
    out = []
    for i in sorted(hit_lines):
        first = min((low[i].find(w) for w in words if w in low[i]), default=0)
        out.append(line_at[i] + first)
    return out


def search(ex: Extract, q: str, limit: int = SEARCH_LIMIT) -> dict[str, Any]:
    q = (q or "").strip()
    if not q:
        raise OutputError(422, "invalid_request", "q: give words, a \"quoted phrase\" or a /regex/")
    starts = _starts(ex, q)
    lines = ex.text.split("\n")
    seen: set[int] = set()
    hits = []
    for off in starts:
        line = ex.line_of(off)
        if line in seen:
            continue
        seen.add(line)
        hit: dict[str, Any] = {"line": line, "offset": off, "text": "\n".join(lines[max(0, line - 2):line + 1])}
        if ex.pages:
            hit["page"] = ex.page_of(off)
        hits.append(hit)
    return {"hits": hits[:max(1, limit)], "total": len(hits)}


# ---- page images --------------------------------------------------------------------

def page_png(src: Path, n: int, width: int, out: Path) -> Path:
    """Render page `n` (1-based) of the PDF `src` at `width` pixels into `out` (kept while newer than `src`)."""
    try:
        if out.exists() and out.stat().st_mtime >= src.stat().st_mtime:
            return out
    except OSError:
        pass
    import pypdfium2 as pdfium

    with _PDFIUM:
        doc = pdfium.PdfDocument(str(src))
        try:
            if not 1 <= n <= len(doc):
                raise no_page(f"No page {n}: the document has {len(doc)} pages")
            page = doc[n - 1]
            im = page.render(scale=width / page.get_width()).to_pil()
            page.close()
        finally:
            doc.close()
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".part")
    im.save(tmp, "PNG")
    os.replace(tmp, out)
    return out
