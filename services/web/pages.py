"""A fetched page → an output (architecture §4.7): HTML becomes markdown with trafilatura (what it loses, code
blocks' languages and blank lines and tables without a header line, put back by htmlmd.py), text and JSON are kept
as they are, PDFs are saved as `document` outputs for the hub's reading tools.

Every saved page is a **hidden** output (`"hidden": true` in its sidecar, plan 30.9): the hub keeps it for the
reading tools, the screening report and citations, but leaves it out of Outputs, the pickers and the library,
which hold what the user made. `hide_saved` marks pages saved before that, once."""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime
from html import unescape
from pathlib import Path
from urllib.parse import urlsplit

import trafilatura

import htmlmd
from safety import Fetched, Refused

HTML_TYPES = {"text/html", "application/xhtml+xml"}
TEXT_TYPES = {"text/plain", "text/markdown", "text/x-markdown"}
JSON_TYPES = {"application/json", "application/ld+json"}
TITLE_RE = re.compile(rb"<title[^>]*>(.*?)</title>", re.I | re.S)
DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
log = logging.getLogger("web")


@dataclass
class Page:
    kind: str             # "text" or "document"
    ext: str              # "md" or "pdf"
    title: str
    text: str             # the markdown (empty for a PDF)
    data: bytes           # what is written
    published: str | None = None
    site: str | None = None


def _decode(body: bytes, charset: str | None) -> str:
    try:
        return body.decode(charset or "utf-8")
    except (LookupError, UnicodeDecodeError):
        return body.decode("utf-8", "replace")


def _html_title(body: bytes) -> str:
    m = TITLE_RE.search(body[:200_000])
    return re.sub(r"\s+", " ", unescape(m[1].decode("utf-8", "replace"))).strip() if m else ""


def _header(title: str, url: str, fetched: str, published: str | None) -> str:
    lines = [f"# {title}", "", f"Source: <{url}>  ", f"Fetched: {fetched}" + ("  " if published else "")]
    if published:
        lines.append(f"Published: {published}")
    return "\n".join(lines) + "\n\n---\n\n"


def convert(f: Fetched, fetched_iso: str) -> Page:
    """Raises Refused(unsupported_type) for images, archives and other binaries."""
    path = urlsplit(f.url).path
    host = urlsplit(f.url).hostname or ""
    if f.content_type == "application/pdf" or f.body.startswith(b"%PDF-"):
        name = Path(path).name
        name = (name[:-4] if name.lower().endswith(".pdf") else name).replace("-", " ").replace("_", " ").strip()
        return Page("document", "pdf", name or host, "", f.body)
    if f.content_type in HTML_TYPES or (not f.content_type and f.body.lstrip()[:15].lower().startswith((b"<!doctype", b"<html"))):
        md = trafilatura.extract(f.body, url=f.url, output_format="markdown", include_links=True, include_tables=True,
                                 include_formatting=True, include_comments=False, favor_recall=True)
        if md:
            md = htmlmd.fix_tables(htmlmd.restore_code(md, htmlmd.code_blocks(f.body)))
        else:       # no main content found: the page's visible text, with its headings, lists, code and tables
            md = htmlmd.plain(f.body) or trafilatura.html2txt(f.body) or ""
        meta = trafilatura.extract_metadata(f.body, default_url=f.url)
        title = (meta.title if meta and meta.title else "") or _html_title(f.body) or host
        published = meta.date if meta and meta.date else None
        site = meta.sitename if meta and meta.sitename else None
        text = _header(title, f.url, fetched_iso, published) + md.strip() + "\n"
        return Page("text", "md", title, text, text.encode(), published, site)
    if f.content_type in TEXT_TYPES or f.content_type in JSON_TYPES or f.content_type.startswith("text/"):
        raw = _decode(f.body, f.charset)
        title = Path(path).name or host
        if f.content_type in JSON_TYPES:
            try:
                raw = json.dumps(json.loads(raw), indent=2, ensure_ascii=False)
            except ValueError:
                pass
            raw = f"```json\n{raw}\n```"
        text = _header(title, f.url, fetched_iso, None) + raw.strip() + "\n"
        return Page("text", "md", title, text, text.encode())
    raise Refused("unsupported_type", f"{f.url} is {f.content_type or 'an unknown type'}, not a web page, text or a PDF",
                  "fetch an HTML page, a text file or a PDF; use view_output for images the hub already has", 415)


def _slug(s: str, n: int) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:n].strip("-")


def save(outputs: Path, page: Page, url: str, final_url: str, content_type: str, dry_run: bool = False) -> Path:
    """`<outputs>/<date>/<HHMMSS>-<host>-<slug>.<ext>` (written as .part, then renamed) and its sidecar."""
    now = datetime.now()
    day = outputs / now.strftime("%Y-%m-%d")
    day.mkdir(parents=True, exist_ok=True)
    host = _slug((urlsplit(final_url).hostname or "page").removeprefix("www."), 40) or "page"
    slug = _slug(page.title, 48)
    base = f"{now.strftime('%H%M%S')}-{host}" + (f"-{slug}" if slug and slug != host else "")
    path = day / f"{base}.{page.ext}"
    n = 2
    while path.exists() or path.with_name(path.name + ".json").exists():
        path, n = day / f"{base}-{n}.{page.ext}", n + 1
    sidecar = {"title": page.title, "kind": page.kind, "url": url, "final_url": final_url,
               "fetched_ts": round(time.time(), 3), "fetched": now.astimezone().isoformat(timespec="seconds"),
               "content_type": content_type, "chars": len(page.text) if page.kind == "text" else None,
               "published": page.published, "site": page.site, "source": {"service": "web", "url": final_url},
               "hidden": True,     # for the agent's reading, not one of the user's outputs (plan 30.9)
               "dry_run": True if dry_run else None}   # from the fake web (plan 26.2)
    for target, data in ((path, page.data),
                         (path.with_name(path.name + ".json"), json.dumps({k: v for k, v in sidecar.items() if v is not None}, indent=1).encode())):
        part = target.with_name(target.name + ".part")
        part.write_bytes(data)
        part.rename(target)
    return path


def hide_saved(outputs: Path) -> int:
    """Mark the sidecars of pages saved before pages were hidden (`<outputs>/<date>/*.json` with no `hidden` key)
    as hidden. A sidecar that says `"hidden": false` is left as it is, so this runs safely any number of times.
    Each is rewritten through a temporary dotfile and a rename (the hub's watcher ignores dotfiles). Returns how
    many were marked."""
    n = 0
    try:
        days = sorted(d for d in outputs.iterdir() if d.is_dir() and DAY_RE.match(d.name))
    except OSError:
        return 0
    for day in days:
        for side in sorted(day.glob("*.json")):
            try:
                data = json.loads(side.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(data, dict) or "hidden" in data or (data.get("source") or {}).get("service") != "web":
                continue
            data["hidden"] = True
            tmp = side.with_name(f".{side.name}.hide")
            try:
                tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
                os.replace(tmp, side)
                n += 1
            except OSError as e:
                log.warning("couldn't mark %s hidden: %s", side, e)
                tmp.unlink(missing_ok=True)
    return n
