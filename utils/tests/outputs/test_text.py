"""Plan 24.2: text extraction from every reader, page offsets, outlines, the cache, deletion, truncation."""

from __future__ import annotations

import json
import os
import shutil

import pytest

from utils.outputs import text
from utils.outputs.describe import output_id
from utils.outputs.index import OutputError
from utils.tests.conftest import FIXTURES

DOCS = FIXTURES / "docs"


def ex(name: str, kind: str = ""):  # `kind` only labels the call; the extension decides
    from utils.outputs.entries import kind_of, subtype_of

    return text.extract(DOCS / name, kind_of(name), subtype_of(name))


def test_pdf_pages_bookmarks_and_markers():
    e = ex("report.pdf")
    assert len(e.pages) == 2 and e.scanned == [] and not e.truncated
    assert e.text.startswith("--- page 1 ---\nIntroduction") and "\f--- page 2 ---\nResults" in e.text
    p1, p2 = (e.text[s:t] for s, t in e.pages)
    assert "spring survey" in p1 and "42 herons" in p2 and "herons" not in p1
    assert [(o["title"], o["page"], o["level"]) for o in e.outline] == [("Introduction", 1, 1), ("Results", 2, 1)]
    assert e.page_of(e.text.index("42 herons")) == 2 and e.page_of(0) == 1
    assert e.tokens == (len(e.text) + 3) // 4 and e.lines == e.text.count("\n") + 1  # no final newline


def test_scanned_pdf_is_flagged():
    e = ex("scanned.pdf")
    assert e.scanned == [1] and len(e.pages) == 1
    assert any("view_output(page=" in n for n in e.notes)


def test_pdf_without_bookmarks_guesses_numbered_headings(tmp_path):
    from utils.tests.fixtures.docs.make import pdf

    p = tmp_path / "numbered.pdf"
    p.write_bytes(pdf(["1. Scope\nThis covers ponds.", "2. Method\nWe walked.\n2.1 Tools\nNets."]))
    e = text.extract(p, "document", "pdf")
    assert [(o["title"], o["level"], o["page"]) for o in e.outline] == [("1. Scope", 1, 1), ("2. Method", 1, 2), ("2.1 Tools", 2, 2)]


def test_docx_headings_and_table():
    e = ex("notes.docx")
    assert "# Field notes" in e.text and "# Overview" in e.text and "## Moons" in e.text
    assert "| Planet | Moons |\n| --- | --- |\n| Mars | 2 |\n| Jupiter | 95 |" in e.text
    assert [(o["level"], o["title"]) for o in e.outline] == [(1, "Field notes"), (1, "Overview"), (2, "Moons")]
    assert all(e.text[o["offset"]:].lstrip("#").strip().startswith(o["title"]) for o in e.outline)


def test_odt_headings_paragraphs_and_table():
    e = ex("minutes.odt")
    assert e.text.startswith("# Minutes\n\nThe meeting opened at nine.") and "## Decisions" in e.text
    assert "| Item | Owner |" in e.text and "| Paint | Ana |" in e.text
    assert [o["title"] for o in e.outline] == ["Minutes", "Decisions"]


def test_epub_follows_the_spine_and_drops_styles():
    e = ex("book.epub")
    assert e.text.index("The Harbor") < e.text.index("The Storm")  # spine order, not manifest order
    assert "boats came in at dawn" in e.text and "color: red" not in e.text
    assert [o["title"] for o in e.outline] == ["The Harbor", "The Storm"]


def test_notebook_cells_outputs_and_dropped_images():
    e = ex("analysis.ipynb", "text")
    assert "# Analysis" in e.text and "```python\ntotal = sum([1, 2, 3])\nprint(total)\n```" in e.text
    assert "Output:\n6" in e.text and "[image output dropped]" in e.text and "iVBOR" not in e.text
    assert [(o["level"], o["title"]) for o in e.outline] == [(1, "Analysis"), (2, "Plot")]
    assert e.text[e.outline[1]["offset"]:].startswith("## Plot")
    assert any("image output" in n for n in e.notes)


def test_html_drops_scripts_and_styles():
    e = ex("garden.html", "text")
    assert "alert" not in e.text and "color: green" not in e.text and "Garden</" not in e.text
    assert "# Garden plan" in e.text and "Plant tomatoes in May." in e.text and "- Spade" in e.text
    assert [o["title"] for o in e.outline] == ["Garden plan", "Tools"]


def test_plain_text_code_csv_and_markdown():
    assert ex("hello.py", "text").text.startswith('"""A tiny module."""') and ex("hello.py").outline == []
    assert ex("people.csv").text == "name,age\nAda,36\nGrace,45\n" and ex("people.csv").lines == 3
    md = ex("readme.md")
    assert [(o["level"], o["title"], o["line"]) for o in md.outline] == [(1, "Readme", 1), (2, "Install", 5), (2, "Use", 9)]


def test_pptx_and_xlsx_point_to_the_sandbox(tmp_path):
    p = tmp_path / "deck.pptx"
    p.write_bytes(b"PK\x03\x04")
    e = text.extract(p, "document", "pptx")
    assert e.text == "" and "sandbox" in e.notes[0]


def test_a_broken_file_gives_a_note(tmp_path):
    p = tmp_path / "bad.pdf"
    p.write_bytes(b"not a pdf")
    e = text.extract(p, "document", "pdf")
    assert e.text == "" and "couldn't read" in e.notes[0]


def test_truncated_at_max_chars(tmp_path, monkeypatch):
    monkeypatch.setattr(text, "MAX_CHARS", 100)
    p = tmp_path / "long.md"
    p.write_text("# Top\n" + "word " * 100 + "\n# Late\n")
    e = text.extract(p, "text", "markdown")
    assert e.truncated and len(e.text) == 100 and [o["title"] for o in e.outline] == ["Top"]


# ---- the cache, through Outputs ----

async def test_cached_reused_and_invalidated(outs, tree):
    shutil.copy(DOCS / "report.pdf", tree.dir / "x.pdf")  # top-level files aren't outputs
    p = tree.put("uploads/2026-10-20/120000-report.pdf", (DOCS / "report.pdf").read_bytes())
    await outs.sync(publish=False)
    oid = output_id("uploads/2026-10-20/120000-report.pdf")
    e = await outs.text(oid)
    cache = text.cache_file(tree.dir, oid)
    assert cache.is_file() and "42 herons" in e.text
    # reused: a planted marker in the cache comes back while the file is unchanged
    data = json.loads(cache.read_text())
    data["ex"]["text"] = "FROM CACHE"
    cache.write_text(json.dumps(data))
    assert (await outs.text(oid)).text == "FROM CACHE"
    # invalidated by a change to the file
    from utils.tests.fixtures.docs.make import pdf

    p.write_bytes(pdf(["Changed page"]))
    os.utime(p, ns=(p.stat().st_mtime_ns + 10**9,) * 2)
    e = await outs.text(oid)
    assert "Changed page" in e.text and len(e.pages) == 1
    # the cache is a dot-folder: never an output
    await outs.sync(publish=False)
    assert not any(".text" in r["path"] for r in await outs.db.fetchall("SELECT path FROM outputs"))


async def test_deleting_the_output_removes_its_cache(outs, tree):
    tree.put("uploads/2026-10-20/120000-readme.md", (DOCS / "readme.md").read_bytes())
    await outs.sync(publish=False)
    oid = output_id("uploads/2026-10-20/120000-readme.md")
    await outs.text(oid)
    (tree.dir / text.PAGES_DIR / oid).mkdir(parents=True)
    assert text.cache_file(tree.dir, oid).exists()
    await outs.delete(oid)
    assert not text.cache_file(tree.dir, oid).exists() and not (tree.dir / text.PAGES_DIR / oid).exists()


async def test_indexing_warms_the_text_and_other_kinds_have_none(outs, tree):
    import asyncio

    tree.put("uploads/2026-10-20/120000-hello.py", (DOCS / "hello.py").read_bytes())
    tree.png("uploads/2026-10-20/120001-pic.png")
    await outs.sync(publish=False)
    oid = output_id("uploads/2026-10-20/120000-hello.py")
    for _ in range(100):
        if text.cache_file(tree.dir, oid).exists():
            break
        await asyncio.sleep(0.02)
    assert text.cache_file(tree.dir, oid).exists()
    with pytest.raises(OutputError) as e:
        await outs.text(output_id("uploads/2026-10-20/120001-pic.png"))
    assert (e.value.status, e.value.code) == (409, "not_text")
