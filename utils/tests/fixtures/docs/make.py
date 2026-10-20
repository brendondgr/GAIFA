"""Writes the document fixtures in this folder (plan 24.1, 24.2): `python utils/tests/fixtures/docs/make.py`.

Every file is built by hand with the standard library and Pillow, so the output is the same on
every run (zip entries carry a fixed date). The PDF writer is importable (`pdf(pages, outline)`)
for tests that need a longer PDF than the fixture.
"""

from __future__ import annotations

import io
import json
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
STAMP = (2026, 10, 20, 12, 0, 0)


# ---- PDF -------------------------------------------------------------------

def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _write_pdf(objs: list[bytes]) -> bytes:
    """Objects 1..n (object 1 is the catalog) → a PDF with an xref table."""
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(out.tell())
        out.write(f"{i} 0 obj\n".encode() + body + b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode())
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write(f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return out.getvalue()


def pdf(pages: list[str], outline: list[tuple[str, int]] = ()) -> bytes:
    """A PDF with one page per string (Helvetica 11 pt, a line per `\\n`) and bookmarks
    `(title, page index)`."""
    n = len(pages)
    # 1 catalog, 2 pages, 3 font, then per page (page, content), then outlines root + items
    page_ids = [4 + 2 * i for i in range(n)]
    out_root = 4 + 2 * n
    objs: list[bytes] = [b"", b"", b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"]
    for i, text in enumerate(pages):
        lines = text.split("\n")
        ops = ["BT", "/F1 11 Tf", "13 TL", "72 760 Td"]
        for k, line in enumerate(lines):
            ops.append(f"({_esc(line)}) Tj" if k == 0 else f"T* ({_esc(line)}) Tj")
        ops.append("ET")
        stream = "\n".join(ops).encode("cp1252", errors="replace")
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> >> /Contents {page_ids[i] + 1} 0 R >>".encode())
        objs.append(f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream")
    objs[1] = f"<< /Type /Pages /Kids [{' '.join(f'{p} 0 R' for p in page_ids)}] /Count {n} >>".encode()
    if outline:
        items = [out_root + 1 + k for k in range(len(outline))]
        objs.append(f"<< /Type /Outlines /First {items[0]} 0 R /Last {items[-1]} 0 R /Count {len(items)} >>".encode())
        for k, (title, page) in enumerate(outline):
            links = (f" /Prev {items[k - 1]} 0 R" if k else "") + (f" /Next {items[k + 1]} 0 R" if k + 1 < len(items) else "")
            objs.append(f"<< /Title ({_esc(title)}) /Parent {out_root} 0 R /Dest [{page_ids[page]} 0 R /XYZ 0 792 0]{links} >>".encode())
        objs[0] = f"<< /Type /Catalog /Pages 2 0 R /Outlines {out_root} 0 R /PageMode /UseOutlines >>".encode()
    else:
        objs[0] = b"<< /Type /Catalog /Pages 2 0 R >>"
    return _write_pdf(objs)


def scanned_pdf() -> bytes:
    """One page that is only a picture of text (no text layer), like a scan."""
    from PIL import Image, ImageDraw

    im = Image.new("RGB", (400, 120), "white")
    ImageDraw.Draw(im).text((20, 50), "A SCANNED PAGE WITH NO TEXT LAYER", fill="black")
    b = io.BytesIO()
    im.save(b, "JPEG", quality=70)
    jpg = b.getvalue()
    content = b"q 400 0 0 120 100 600 cm /Im1 Do Q"
    return _write_pdf([
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /XObject << /Im1 4 0 R >> >> /Contents 5 0 R >>",
        f"<< /Type /XObject /Subtype /Image /Width 400 /Height 120 /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length {len(jpg)} >>\nstream\n".encode() + jpg + b"\nendstream",
        f"<< /Length {len(content)} >>\nstream\n".encode() + content + b"\nendstream",
    ])


# ---- zips ------------------------------------------------------------------

def _zip(files: list[tuple[str, str | bytes]], stored_first: bool = False) -> bytes:
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        for k, (name, data) in enumerate(files):
            info = zipfile.ZipInfo(name, STAMP)
            info.compress_type = zipfile.ZIP_STORED if stored_first and k == 0 else zipfile.ZIP_DEFLATED
            z.writestr(info, data)
    return b.getvalue()


W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def _wp(text: str, style: str | None = None) -> str:
    ppr = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    return f"<w:p>{ppr}<w:r><w:t>{text}</w:t></w:r></w:p>"


def docx() -> bytes:
    cell = lambda t: f"<w:tc><w:p><w:r><w:t>{t}</w:t></w:r></w:p></w:tc>"  # noqa: E731
    table = "<w:tbl>" + "".join("<w:tr>" + "".join(cell(c) for c in row) + "</w:tr>" for row in
                                (("Planet", "Moons"), ("Mars", "2"), ("Jupiter", "95"))) + "</w:tbl>"
    body = (_wp("Field notes", "Title") + _wp("Overview", "Heading1") + _wp("The survey covered three sites in October.")
            + _wp("Moons", "Heading2") + table + _wp("Jupiter has the most moons in this table."))
    return _zip([
        ("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
         '<Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" '
         'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>'),
        ("word/document.xml", f'<?xml version="1.0"?><w:document {W}><w:body>{body}</w:body></w:document>'),
    ])


def odt() -> bytes:
    ns = ('xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
          'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0"')
    body = ('<text:h text:outline-level="1">Minutes</text:h><text:p>The meeting opened at nine.</text:p>'
            '<text:h text:outline-level="2">Decisions</text:h><text:p>Paint the shed green.</text:p>'
            '<table:table><table:table-row><table:table-cell><text:p>Item</text:p></table:table-cell><table:table-cell><text:p>Owner</text:p></table:table-cell></table:table-row>'
            '<table:table-row><table:table-cell><text:p>Paint</text:p></table:table-cell><table:table-cell><text:p>Ana</text:p></table:table-cell></table:table-row></table:table>')
    return _zip([
        ("mimetype", "application/vnd.oasis.opendocument.text"),
        ("content.xml", f'<?xml version="1.0"?><office:document-content {ns}><office:body><office:text>{body}</office:text></office:body></office:document-content>'),
    ], stored_first=True)


def epub() -> bytes:
    chap = lambda title, text: (f'<?xml version="1.0"?><html xmlns="http://www.w3.org/1999/xhtml"><head><title>{title}</title>'  # noqa: E731
                                f"<style>p {{ color: red }}</style></head><body><h1>{title}</h1><p>{text}</p></body></html>")
    return _zip([
        ("mimetype", "application/epub+zip"),
        ("META-INF/container.xml", '<?xml version="1.0"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
         '<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>'),
        ("OEBPS/content.opf", '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0"><metadata/>'
         '<manifest><item id="c2" href="text/two.xhtml" media-type="application/xhtml+xml"/>'
         '<item id="c1" href="text/one.xhtml" media-type="application/xhtml+xml"/></manifest>'
         '<spine><itemref idref="c1"/><itemref idref="c2"/></spine></package>'),
        ("OEBPS/text/one.xhtml", chap("The Harbor", "The boats came in at dawn.")),
        ("OEBPS/text/two.xhtml", chap("The Storm", "By noon the wind had turned.")),
    ], stored_first=True)


# ---- text ------------------------------------------------------------------

def ipynb() -> str:
    return json.dumps({"nbformat": 4, "nbformat_minor": 5, "metadata": {"language_info": {"name": "python"}}, "cells": [
        {"cell_type": "markdown", "metadata": {}, "source": ["# Analysis\n", "Load the numbers."]},
        {"cell_type": "code", "metadata": {}, "execution_count": 1, "source": ["total = sum([1, 2, 3])\n", "print(total)"],
         "outputs": [{"output_type": "stream", "name": "stdout", "text": ["6\n"]}]},
        {"cell_type": "markdown", "metadata": {}, "source": ["## Plot"]},
        {"cell_type": "code", "metadata": {}, "execution_count": 2, "source": ["plot(total)"],
         "outputs": [{"output_type": "display_data", "data": {"image/png": "iVBORw0KGgo=", "text/plain": ["<Figure>"]}, "metadata": {}}]},
    ]}, indent=1)


HTML = """<!doctype html>
<html><head><title>Garden</title><style>body { color: green }</style>
<script>alert("never shown")</script></head>
<body><h1>Garden plan</h1><p>Plant <b>tomatoes</b> in May.</p>
<h2>Tools</h2><ul><li>Spade</li><li>Hose</li></ul></body></html>
"""
CSV = "name,age\nAda,36\nGrace,45\n"
PY = '''"""A tiny module."""


def greet(name: str) -> str:
    # say hello
    return f"Hello, {name}!"
'''
MD = "# Readme\n\nIntro text.\n\n## Install\n\nRun `make`.\n\n## Use\n\nCall greet.\n"

REPORT = [
    "Introduction\nThis report covers the spring survey.\nThe lake was clear.",
    "Results\nWe counted 42 herons.\nThe water was 14 degrees.",
]


def build() -> dict[str, bytes]:
    return {
        "report.pdf": pdf(REPORT, [("Introduction", 0), ("Results", 1)]),
        "scanned.pdf": scanned_pdf(),
        "notes.docx": docx(), "minutes.odt": odt(), "book.epub": epub(),
        "analysis.ipynb": ipynb().encode(), "garden.html": HTML.encode(), "people.csv": CSV.encode(),
        "hello.py": PY.encode(), "readme.md": MD.encode(),
    }


if __name__ == "__main__":
    for name, data in build().items():
        (HERE / name).write_bytes(data)
        print(f"{name}: {len(data)} bytes", file=sys.stderr)
