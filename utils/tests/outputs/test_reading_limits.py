"""Limits on reading documents: zip bombs, huge ODF spaces, tall PDF pages, many search hits."""

from __future__ import annotations

import threading
import time
import zipfile

from PIL import Image

from utils.outputs import readers, reading, text
from utils.outputs.text import Extract
from utils.tests.fixtures.docs.make import pdf

W = '<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
O = ('<?xml version="1.0"?><office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
     'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">')


def zipped(tmp_path, name: str, files: dict[str, str]):
    p = tmp_path / name
    with zipfile.ZipFile(p, "w", zipfile.ZIP_DEFLATED) as z:
        for k, v in files.items():
            z.writestr(k, v)
    return p


def docx(tmp_path, body: str):
    return zipped(tmp_path, "x.docx", {"word/document.xml": W + body + "</w:body></w:document>"})


def para(s: str) -> str:
    return f"<w:p><w:r><w:t>{s}</w:t></w:r></w:p>"


# ---- docx / odt / epub ----

def test_odt_spaces_are_capped(tmp_path):
    p = zipped(tmp_path, "s.odt", {"content.xml": O + "<office:body><office:text><text:p>a"
                                   + '<text:s text:c="100000"/>' * 3 + '<text:s text:c="x"/>b</text:p></office:text></office:body></office:document-content>'})
    e = text.extract(p, "document", "odt")
    assert e.text == "a" + " " * (3 * readers.SPACES + 1) + "b"


def test_odt_blocks_in_order_and_without_a_text_body(tmp_path):
    body = ('<text:h text:outline-level="2">Top</text:h><text:section><text:p>one</text:p>'
            '<text:list><text:list-item><text:p>two</text:p></text:list-item></text:list></text:section><text:p>three</text:p>')
    p = zipped(tmp_path, "a.odt", {"content.xml": O + "<office:automatic-styles><text:p>style</text:p></office:automatic-styles>"
                                   "<office:body><office:text>" + body + "</office:text></office:body></office:document-content>"})
    r = readers.read(p, "document", "odt")
    assert r.text == "## Top\n\none\n\n- two\n\nthree" and r.headings == [(2, "Top", 0)]
    p = zipped(tmp_path, "b.odt", {"content.xml": O + "<x><text:p>loose</text:p></x></office:document-content>"})
    assert readers.read(p, "document", "odt").text == "loose"  # no office:text: read from anywhere


def test_many_blocks_read_in_order_while_dropped_in_batches(tmp_path):
    words = [f"para {i}" for i in range(3000)]
    want = "\n\n".join(words)
    assert readers.read(docx(tmp_path, "".join(para(w) for w in words)), "document", "docx").text == want
    p = zipped(tmp_path, "m.odt", {"content.xml": O + "<office:body><office:text>" + "".join(f"<text:p>{w}</text:p><x/>" for w in words)
                                   + "</office:text></office:body></office:document-content>"})
    assert readers.read(p, "document", "odt").text == want


def test_a_zip_member_unpacks_only_up_to_the_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(readers, "MAX_MEMBER", 64 * 1024)
    p = docx(tmp_path, "".join(para(f"paragraph {i}") for i in range(40_000)))  # ~1.6 MB unpacked, a few KB packed
    e = text.extract(p, "document", "docx")
    assert e.text.startswith("paragraph 0\n\nparagraph 1") and 1000 < len(e.text) < 64 * 1024
    assert any("stopped reading word/document.xml after 0 MB unpacked" in n for n in e.notes)


def test_an_epub_unpacks_only_up_to_the_document_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(readers, "MAX_UNZIP", 100_000)
    chapter = "<html><body>" + "<p>words and more words</p>" * 2000 + "</body></html>"  # ~54 KB each
    opf = ('<package xmlns="http://www.idpf.org/2007/opf"><manifest>' + "".join(f'<item id="c{i}" href="c{i}.html"/>' for i in range(5))
           + "</manifest><spine>" + "".join(f'<itemref idref="c{i}"/>' for i in range(5)) + "</spine></package>")
    p = zipped(tmp_path, "b.epub", {"META-INF/container.xml": '<container><rootfiles><rootfile full-path="b.opf"/></rootfiles></container>',
                                    "b.opf": opf, **{f"c{i}.html": chapter for i in range(5)}})
    e = text.extract(p, "document", "epub")
    assert 2000 < e.text.count("words and more words") < 2 * 2000 * 2  # the first chapter whole, part of the second, then none
    assert any("stopped reading c1.html" in n for n in e.notes)


def test_docx_stops_once_it_has_enough_text(tmp_path, monkeypatch):
    monkeypatch.setattr(readers, "MAX_TEXT", 1000)
    p = docx(tmp_path, "".join(para(f"paragraph {i}") for i in range(50_000)))
    r = readers.read(p, "document", "docx")
    assert 1000 < len(r.text) < 1100 and not r.notes  # text.extract cuts it at MAX_CHARS and says so


def test_odt_stops_once_it_has_enough_text(tmp_path, monkeypatch):
    monkeypatch.setattr(readers, "MAX_TEXT", 1000)
    p = zipped(tmp_path, "l.odt", {"content.xml": O + "<office:body><office:text>" + "<text:p>a line of text</text:p>" * 50_000
                                   + "</office:text></office:body></office:document-content>"})
    assert 1000 < len(readers.read(p, "document", "odt").text) < 1100


def test_one_huge_paragraph_stops_the_reader(tmp_path, monkeypatch):
    monkeypatch.setattr(readers, "MAX_PARTS", 1000)
    p = docx(tmp_path, para("before") + "<w:p>" + "<w:r><w:t>ab</w:t></w:r>" * 5000 + "</w:p>" + para("after"))
    r = readers.read(p, "document", "docx")
    assert r.text == "before" and "more than 1,000 XML elements" in r.notes[0]


# ---- PDF ----

def one_page_pdf(w: int, h: int) -> bytes:
    return (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
            + f"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 {w} {h}]>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n".encode())


def test_a_tall_page_renders_within_the_caps(tmp_path):
    src = tmp_path / "tall.pdf"
    src.write_bytes(one_page_pdf(10, 14400))  # at width 64: 64 × 92,160 px before
    im = Image.open(reading.page_png(src, 1, 64, tmp_path / "t.png"))
    assert im.size[1] <= reading.MAX_PAGE_SIDE and im.size[0] <= 64


def test_page_pixels_are_capped(tmp_path, monkeypatch):
    monkeypatch.setattr(reading, "MAX_PAGE_PX", 100_000)
    src = tmp_path / "a.pdf"
    src.write_bytes(pdf(["Hello"]))
    w, h = Image.open(reading.page_png(src, 1, 1200, tmp_path / "a.png")).size
    assert w * h <= 101_000 and abs(w / h - 612 / 792) < 0.02


def test_page_scale():
    assert reading.page_scale(612, 792, 300) == 300 / 612  # an ordinary page is untouched
    assert reading.page_scale(612, 792, 10**6) == reading.page_scale(612, 792, reading.MAX_PAGE_WIDTH)
    assert reading.page_scale(0, 0, 200) > 0  # no division by zero


def test_pdf_reads_at_most_max_pages(tmp_path, monkeypatch):
    monkeypatch.setattr(readers, "MAX_PDF_PAGES", 2)
    p = tmp_path / "four.pdf"
    p.write_bytes(pdf([f"Page {i}" for i in range(1, 5)]))
    r = readers.read(p, "document", "pdf")
    assert len(r.pages) == 2 and "Page 2" in r.text and "Page 3" not in r.text
    assert "read the first 2 of 4 pages" in r.notes


# ---- search ----

def lines_extract(n: int) -> Extract:
    return Extract(text="the quick line\n" * n + "end", lines=n + 1)


def test_search_hits_are_capped_and_lines_right(monkeypatch):
    monkeypatch.setattr(reading, "MAX_MATCHES", 100)
    ex = lines_extract(1000)
    for q in ("quick", '"quick line"', "/qu.ck/"):
        r = reading.search(ex, q, 5)
        assert r["total"] == 100 and r["capped"] is True, q
        assert [h["line"] for h in r["hits"]] == [1, 2, 3, 4, 5] == [ex.line_of(h["offset"]) for h in r["hits"]]
    r = reading.search(ex, "end", 5)
    assert r == {"hits": [{"line": 1001, "offset": 15_000, "text": "the quick line\nend"}], "total": 1}


def test_search_of_many_lines_is_quick():
    ex, out = lines_extract(250_000), {}
    t = time.monotonic()
    th = threading.Thread(target=lambda: out.update(reading.search(ex, "quick", 20)), daemon=True)
    th.start()
    th.join(10)
    assert out.get("total") == reading.MAX_MATCHES and out["capped"], f"still running after {time.monotonic() - t:.0f} s"
    assert time.monotonic() - t < 5


def test_a_capped_regex_says_so():
    r = reading.search(Extract(text="ab\n" * (reading.MAX_MATCHES + 10)), "/b/", 3)
    assert r["total"] == reading.MAX_MATCHES and r["capped"]
    assert "capped" not in reading.search(Extract(text="ab\n" * 10), "/b/", 3)
