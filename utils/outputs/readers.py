"""Readers for `text.extract` (plan 24.2): one file → `Read` (text, page offsets, headings, notes).

- **PDF** via `pypdfium2`: each page starts with `\\f--- page N ---` (no `\\f` before the first),
  bookmarks are the outline (else numbered heading lines are guessed), pages with almost no
  text are `scanned`.
- **docx / odt**: `zipfile` + `xml.etree`; heading styles become `#` lines, tables markdown tables.
- **epub**: the spine's documents in order, each through the HTML reader.
- **HTML**: `html.parser`; scripts, styles and the head are dropped; `h1`–`h6` become `#` lines.
- **ipynb**: markdown cells as they are, code cells fenced, text outputs after them, images
  dropped with a note.
- **pptx / xlsx**: no text here; the workspace sandbox reads them (Phase 27).
- Anything else is read as text (UTF-8, or UTF-16 with a BOM).

Limits, so a small file can't take the hub's memory: a zip is unpacked at most `MAX_MEMBER` bytes a
file and `MAX_UNZIP` a document (counted as they come: a member's declared size can lie), its XML
is parsed as it unpacks and each paragraph or table dropped once read (at most `MAX_PARTS` elements
in one), a reader stops past `MAX_TEXT` characters, a PDF past `MAX_PDF_PAGES` pages, and an ODF
`<text:s text:c=…/>` gives at most `SPACES` spaces. Past a limit the reader keeps what it read, with
a note.

Headings are `(level, title, offset)`; `text.py` turns them into the outline.
"""

from __future__ import annotations

import json
import re
import threading
import zipfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree as ET

from utils.outputs.upload import as_text

SCANNED_CHARS = 20  # a PDF page with fewer characters than this is probably a scan
_PDFIUM = threading.Lock()  # pdfium is not thread-safe
MAX_TEXT = 4_100_000  # a reader stops past this; `text.MAX_CHARS` (4 M) then cuts the text and says so
MAX_MEMBER = 50 * 2**20  # bytes unpacked from one file in a docx / odt / epub
MAX_UNZIP = 200 * 2**20  # ... and from the whole document
MAX_PARTS = 500_000  # XML elements in one paragraph or table
MAX_PDF_PAGES = 20_000
SPACES = 100  # most spaces one ODF <text:s text:c=…/> gives
_CHUNK = 2**20


@dataclass
class Read:
    text: str = ""
    pages: list[tuple[int, int]] = field(default_factory=list)
    headings: list[tuple[int, str, int]] = field(default_factory=list)  # (level, title, offset)
    scanned: list[int] = field(default_factory=list)  # 1-based pages
    notes: list[str] = field(default_factory=list)


class _Out:
    """Text built up block by block, with headings at their offsets."""

    def __init__(self) -> None:
        self.parts: list[str] = []
        self.n = 0
        self.headings: list[tuple[int, str, int]] = []

    def add(self, s: str) -> None:
        self.parts.append(s)
        self.n += len(s)

    def block(self, s: str) -> int | None:
        """Adds a paragraph; returns where it starts (None when it was empty)."""
        s = s.strip("\n")
        if not s.strip():
            return None
        if self.n:
            self.add("\n\n")
        start = self.n
        self.add(s)
        return start

    def heading(self, level: int, title: str) -> None:
        title = " ".join(title.split())
        if not title:
            return
        if self.n:
            self.add("\n\n")
        self.headings.append((level, title, self.n))
        self.add("#" * level + " " + title)

    def read(self) -> Read:
        return Read("".join(self.parts), headings=self.headings)


class _Zip:
    """A document's zip, unpacked with a cap (`MAX_MEMBER`, `MAX_UNZIP`); past it a member just ends
    early and a note says so."""

    def __init__(self, z: zipfile.ZipFile) -> None:
        self.z, self.left, self.notes = z, MAX_UNZIP, []

    def chunks(self, name: str) -> Iterator[bytes]:
        info = self.z.getinfo(name)  # KeyError when it's missing
        cap, n, cut = min(MAX_MEMBER, self.left), 0, False
        try:
            with self.z.open(info) as f:
                while n < cap and (b := f.read(min(_CHUNK, cap - n))):
                    n += len(b)
                    yield b
                cut = n >= cap and (info.file_size > n or bool(f.read(1)))
        finally:
            self.left -= n
        if cut:
            self.notes.append(f"stopped reading {name} after {n / 2**20:.0f} MB unpacked (at most {MAX_MEMBER // 2**20} MB "
                              f"a file, {MAX_UNZIP // 2**20} MB a document)")

    def read(self, name: str) -> bytes:
        return b"".join(self.chunks(name))

    def xml(self, name: str) -> Iterator[tuple[str, ET.Element]]:
        """`start` / `end` events of a member's XML, parsed as it unpacks (a cut member just ends)."""
        parser, before = ET.XMLPullParser(("start", "end")), len(self.notes)
        for b in self.chunks(name):
            parser.feed(b)
            yield from parser.read_events()
        if len(self.notes) == before:
            parser.close()
            yield from parser.read_events()

    def blocks(self, name: str, is_block: Callable[[ET.Element, list[ET.Element]], bool]) -> Iterator[tuple[ET.Element, list[ET.Element]]]:
        """The outermost blocks of a member's XML (`is_block(element, its ancestors)`: paragraphs, tables),
        each with its ancestors once it ends. What has been read is then dropped, in batches (one at a
        time is quadratic), so memory holds about one block; one past `MAX_PARTS` elements ends it."""
        stack: list[ET.Element] = []
        done: list[int] = []  # how many of each open element's first children are read
        inside = parts = 0  # open blocks; elements in the current one
        for ev, el in self.xml(name):
            if ev == "start":
                inside += is_block(el, stack)
                stack.append(el)
                done.append(0)
                parts += inside > 0
                if parts > MAX_PARTS:
                    self.notes.append(f"a paragraph or table has more than {MAX_PARTS:,} XML elements; stopped reading there")
                    return
                continue
            stack.pop()
            done.pop()
            if is_block(el, stack):
                inside -= 1
                if not inside:
                    yield el, stack
                    parts = 0
            if not inside and stack:
                done[-1] += 1
                if done[-1] >= 1024:
                    del stack[-1][:done[-1]]
                    done[-1] = 0


def md_table(rows: list[list[str]]) -> str:
    rows = [[" ".join(c.split()).replace("|", "\\|") for c in r] for r in rows if r]
    if not rows:
        return ""
    w = max(len(r) for r in rows)
    rows = [r + [""] * (w - len(r)) for r in rows]
    return "\n".join(["| " + " | ".join(rows[0]) + " |", "|" + " --- |" * w] + ["| " + " | ".join(r) + " |" for r in rows[1:]])


# ---- PDF ----------------------------------------------------------------------

_NUMBERED = re.compile(r"^(\d+(?:\.\d+){0,3})\.?\s+([A-Z][^\n]{1,70})$")


def read_pdf(p: Path) -> Read:
    import pypdfium2 as pdfium

    out = Read()
    parts: list[str] = []
    n = 0
    with _PDFIUM:
        doc = pdfium.PdfDocument(str(p))
        try:
            total = len(doc)
            for i in range(min(total, MAX_PDF_PAGES)):
                if n > MAX_TEXT:
                    break
                page = doc[i]
                tp = page.get_textpage()
                body = tp.get_text_range().replace("\r\n", "\n").replace("\r", "\n").strip("\n")
                tp.close()
                page.close()
                head = ("\f" if i else "") + f"--- page {i + 1} ---\n"
                start = n
                parts += [head, body]
                n += len(head) + len(body)
                out.pages.append((start, n))
                if len(body.strip()) < SCANNED_CHARS:
                    out.scanned.append(i + 1)
            marks = []
            for b in doc.get_toc(max_depth=6):
                dest = b.get_dest()
                idx = dest.get_index() if dest is not None else None
                if idx is not None and 0 <= idx < len(out.pages):
                    marks.append((b.level + 1, b.get_title() or "", out.pages[idx][0]))
        finally:
            doc.close()
    out.text = "".join(parts)
    if total > MAX_PDF_PAGES:
        out.notes.append(f"read the first {MAX_PDF_PAGES:,} of {total:,} pages")
    if marks:
        out.headings = marks
    else:
        for (s, e) in out.pages:
            pos = s
            for line in out.text[s:e].split("\n"):
                m = _NUMBERED.match(line.strip())
                if m:
                    out.headings.append((m[1].count(".") + 1, line.strip(), pos))
                pos += len(line) + 1
    if out.scanned:
        out.notes.append(f"{len(out.scanned)} of {len(out.pages)} pages have no text layer (scanned?); "
                         "look at them as images with view_output(page=…)")
    return out


# ---- docx / odt -----------------------------------------------------------------

WNS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_HEAD_STYLE = re.compile(r"^heading\s*(\d)$", re.I)


def _w_text(el: ET.Element) -> str:
    out = []
    for e in el.iter():
        if e.tag == WNS + "t" and e.text:
            out.append(e.text)
        elif e.tag == WNS + "tab":
            out.append("\t")
        elif e.tag in (WNS + "br", WNS + "cr"):
            out.append("\n")
    return "".join(out)


def _docx_block(el: ET.Element, o: _Out) -> None:
    if el.tag == WNS + "p":
        style = el.find(f"{WNS}pPr/{WNS}pStyle")
        name = (style.get(WNS + "val") if style is not None else "") or ""
        m = _HEAD_STYLE.match(name)
        text = _w_text(el)
        if name.lower() == "title":
            o.heading(1, text)
        elif m:
            o.heading(min(max(int(m[1]), 1), 6), text)
        else:
            o.block(text)
    elif el.tag == WNS + "tbl":
        o.block(md_table([[_w_text(c) for c in tr.findall(WNS + "tc")] for tr in el.findall(WNS + "tr")]))


def read_docx(p: Path) -> Read:
    o = _Out()
    with zipfile.ZipFile(p) as z:
        zr = _Zip(z)
        for el, up in zr.blocks("word/document.xml", lambda el, up: len(up) == 2):  # a child of the root's child
            if up[1].tag == WNS + "body":
                _docx_block(el, o)
                if o.n > MAX_TEXT:
                    break
    r = o.read()
    r.notes += zr.notes
    return r


ONS = {"text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0", "table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
       "office": "urn:oasis:names:tc:opendocument:xmlns:office:1.0"}


def _q(prefix: str, tag: str) -> str:
    return "{" + ONS[prefix] + "}" + tag


def _spaces(c: str | None) -> str:
    try:
        n = int(c or 1)
    except ValueError:
        n = 1
    return " " * min(max(n, 0), SPACES)


def _o_text(el: ET.Element) -> str:
    out = [el.text or ""]
    for c in el:
        if c.tag == _q("text", "s"):
            out.append(_spaces(c.get(_q("text", "c"))))
        elif c.tag == _q("text", "tab"):
            out.append("\t")
        elif c.tag == _q("text", "line-break"):
            out.append("\n")
        else:
            out.append(_o_text(c))
        out.append(c.tail or "")
    return "".join(out)


_O_BLOCKS = {_q("text", "h"), _q("text", "p"), _q("text", "list"), _q("table", "table")}


def _odt_block(c: ET.Element, o: _Out) -> None:
    if c.tag == _q("text", "h"):
        o.heading(min(int(c.get(_q("text", "outline-level"), "1")), 6), _o_text(c))
    elif c.tag == _q("text", "p"):
        o.block(_o_text(c))
    elif c.tag == _q("text", "list"):
        items = ["- " + " ".join(_o_text(p) for p in li.iter(_q("text", "p"))) for li in c.findall(_q("text", "list-item"))]
        o.block("\n".join(items))
    elif c.tag == _q("table", "table"):
        rows = [[" ".join(_o_text(p) for p in cell.iter(_q("text", "p"))) for cell in r.findall(_q("table", "table-cell"))]
                for r in c.iter(_q("table", "table-row"))]
        o.block(md_table(rows))


def _in_text(up: list[ET.Element]) -> bool:
    return len(up) > 2 and up[1].tag == _q("office", "body") and up[2].tag == _q("office", "text")


def read_odt(p: Path) -> Read:
    """Headings, paragraphs, lists and tables (not inside another one) in office:body/office:text, else
    anywhere."""
    o, other = _Out(), _Out()  # `other`: blocks outside office:body/office:text, for a file without one
    has_text = False

    def is_block(el: ET.Element, up: list[ET.Element]) -> bool:
        nonlocal has_text
        has_text = has_text or (len(up) == 2 and el.tag == _q("office", "text") and up[1].tag == _q("office", "body"))
        return el.tag in _O_BLOCKS

    with zipfile.ZipFile(p) as z:
        zr = _Zip(z)
        for el, up in zr.blocks("content.xml", is_block):
            out = o if _in_text(up) else other
            _odt_block(el, out)
            if out.n > MAX_TEXT:
                break
    r = (o if has_text else other).read()
    r.notes += zr.notes
    return r


# ---- HTML and epub ----------------------------------------------------------------

class _Html(HTMLParser):
    SKIP = {"script", "style", "head", "noscript", "template", "svg"}
    BLOCK = {"p", "div", "section", "article", "header", "footer", "main", "nav", "aside", "blockquote", "pre", "table",
             "ul", "ol", "dl", "figure", "figcaption", "form", "hr", "tr", "br"}

    def __init__(self, o: _Out) -> None:
        super().__init__(convert_charrefs=True)
        self.o, self.skip, self.buf, self.head, self.pre = o, 0, [], 0, 0

    def flush(self) -> None:
        s = "".join(self.buf)
        self.buf = []
        if self.head:
            return
        s = s if self.pre else re.sub(r"[ \t\r\f\v]+", " ", s)
        s = "\n".join(x.strip() if not self.pre else x for x in s.split("\n"))
        self.o.block(re.sub(r"\n{3,}", "\n\n", s))

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in self.SKIP:
            self.skip += 1
        elif self.skip:
            return
        elif re.fullmatch(r"h[1-6]", tag):
            self.flush()
            self.head = int(tag[1])
        elif tag == "li":
            self.flush()
            self.buf.append("- ")
        elif tag in ("td", "th"):
            self.buf.append(" | ")
        elif tag in self.BLOCK:
            if tag == "pre":
                self.pre += 1
            self.flush() if tag != "br" else self.buf.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP:
            self.skip = max(0, self.skip - 1)
        elif self.skip:
            return
        elif re.fullmatch(r"h[1-6]", tag) and self.head:
            level, self.head = self.head, 0
            self.o.heading(level, "".join(self.buf))
            self.buf = []
        elif tag in self.BLOCK or tag == "li":
            self.flush()
            if tag == "pre":
                self.pre = max(0, self.pre - 1)

    def handle_data(self, data: str) -> None:
        if not self.skip:
            self.buf.append(data)

    def close(self) -> None:
        super().close()
        self.flush()


def html_into(text: str, o: _Out) -> None:
    h = _Html(o)
    h.feed(text)
    h.close()


def read_html_text(text: str) -> Read:
    o = _Out()
    html_into(text, o)
    return o.read()


def read_epub(p: Path) -> Read:
    o = _Out()
    with zipfile.ZipFile(p) as z:
        zr = _Zip(z)
        cont = ET.fromstring(zr.read("META-INF/container.xml"))
        rf = next((e for e in cont.iter() if e.tag.endswith("rootfile")), None)
        opf_path = rf.get("full-path") if rf is not None else None
        if not opf_path:
            return Read(notes=["no package document in META-INF/container.xml"])
        opf = ET.fromstring(zr.read(opf_path))
        base = PurePosixPath(opf_path).parent
        manifest = {e.get("id"): e.get("href") for e in opf.iter() if e.tag.endswith("}item")}
        for ref in (e for e in opf.iter() if e.tag.endswith("}itemref")):
            if o.n > MAX_TEXT or zr.left <= 0:
                break
            href = manifest.get(ref.get("idref"))
            if not href:
                continue
            try:
                raw = zr.read(str(base / href.split("#")[0]) if str(base) != "." else href.split("#")[0])
            except KeyError:
                continue
            html_into(raw.decode("utf-8", errors="replace"), o)
    r = o.read()
    r.notes += zr.notes
    return r


# ---- notebooks and plain text --------------------------------------------------------

def _src(v: object) -> str:
    return "".join(v) if isinstance(v, list) else str(v or "")


def read_ipynb(text: str) -> Read:
    try:
        nb = json.loads(text)
    except ValueError:
        return Read(text, notes=["not valid notebook JSON; read as text"])
    lang = (nb.get("metadata", {}).get("language_info") or {}).get("name") or (nb.get("metadata", {}).get("kernelspec") or {}).get("language") or ""
    o = _Out()
    dropped = 0
    for cell in nb.get("cells", []):
        src = _src(cell.get("source")).rstrip()
        if cell.get("cell_type") == "markdown":
            src = src.strip("\n")
            if (start := o.block(src)) is not None:
                o.headings += [(lv, t, start + off) for lv, t, off in markdown_headings(src)]
        elif cell.get("cell_type") == "code":
            o.block(f"```{lang}\n{src}\n```")
            outs = []
            for out in cell.get("outputs", []):
                t = out.get("output_type")
                if t == "stream":
                    outs.append(_src(out.get("text")))
                elif t in ("execute_result", "display_data"):
                    data = out.get("data", {})
                    if any(k.startswith("image/") for k in data):
                        dropped += 1
                        outs.append("[image output dropped]")
                    elif "text/plain" in data:
                        outs.append(_src(data["text/plain"]))
                elif t == "error":
                    outs.append(f"{out.get('ename', 'Error')}: {out.get('evalue', '')}")
            if outs:
                o.block("Output:\n" + "\n".join(x.rstrip() for x in outs))
        else:
            o.block(src)
    r = o.read()
    if dropped:
        r.notes.append(f"{dropped} image output(s) dropped")
    return r


def markdown_headings(text: str) -> list[tuple[int, str, int]]:
    out, pos, fence = [], 0, False
    for line in text.split("\n"):
        if line.lstrip().startswith(("```", "~~~")):
            fence = not fence
        elif not fence and (m := re.match(r"^(#{1,6})\s+(.+?)\s*#*\s*$", line)):
            out.append((len(m[1]), m[2], pos))
        pos += len(line) + 1
    return out


def read_text(p: Path, subtype: str | None) -> Read:
    text = as_text(p.read_bytes())
    if text is None:
        return Read(notes=["not a text file (not UTF-8, or UTF-16 with a BOM)"])
    text = text.replace("\r\n", "\n")
    if subtype == "notebook":
        return read_ipynb(text)
    if subtype == "web:html":
        return read_html_text(text)
    return Read(text, headings=markdown_headings(text) if subtype == "markdown" else [])


def read(p: Path, kind: str, subtype: str | None) -> Read:
    ext = (subtype or "").lower()
    if kind == "document":
        if ext == "pdf":
            return read_pdf(p)
        if ext == "docx":
            return read_docx(p)
        if ext == "odt":
            return read_odt(p)
        if ext == "epub":
            return read_epub(p)
        return Read(notes=[f"{ext or 'this file'}: the hub doesn't read it; the workspace sandbox can (plan 27)"])
    return read_text(p, subtype)
