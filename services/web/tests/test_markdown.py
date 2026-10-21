"""Plan 30.8: pages become good markdown: code blocks keep their language and blank lines, tables render (layout
tables without a header line become paragraphs), and a page without main content keeps its structure."""

from __future__ import annotations

from types import SimpleNamespace

import htmlmd
import pages

DOC = b"""<!doctype html><html><head><title>Guide to tides</title></head><body>
<nav><a href="/">Home</a> <a href="/x">X</a></nav>
<article>
<h1>Guide to tides</h1>
<p>Tides are the rise and fall of sea levels caused by the <b>Moon</b> and the <i>Sun</i>. See <a href="https://example.org/more">more</a>.</p>
<h2>Install</h2>
<p>Run this command to install the tool:</p>
<pre><code class="language-bash">pip install tides
tides --port 8080</code></pre>
<p>Then use <code>tides.now()</code> in Python:</p>
<div class="highlight highlight-source-python"><pre><span class="pl-k">import</span> tides

<span class="pl-k">def</span> high(x):
    return x * 2  # double</pre></div>
<h2>Table of heights</h2>
<table><thead><tr><th>Place</th><th>Height (m)</th></tr></thead>
<tbody><tr><td>Bay of Fundy</td><td>16.3</td></tr><tr><td>Bristol Channel</td><td>14.5</td></tr></tbody></table>
<h3>Notes</h3>
<ul><li>First item</li><li>Second item</li></ul>
<p>Last paragraph of the article with enough words to look like content to the extractor, really.</p>
</article>
<footer>Copyright</footer>
</body></html>"""


def convert(body: bytes) -> str:
    f = SimpleNamespace(url="https://example.org/tides", content_type="text/html", body=body, charset="utf-8")
    return pages.convert(f, "2026-10-21T10:00:00-04:00").text


def test_code_blocks_keep_their_language_and_blank_lines():
    """Before: ``` without a language, and `import tides` glued to `def high` (the blank line dropped)."""
    md = convert(DOC)
    assert "```bash\npip install tides\ntides --port 8080\n```\n\nThen use `tides.now()`" in md
    assert "```python\nimport tides\n\ndef high(x):\n    return x * 2  # double\n```\n\n## Table of heights" in md
    assert "| Place | Height (m) |" in md and "|---|---|" in md and "| Bay of Fundy | 16.3 |" in md
    assert md.count("# Guide to tides") == 2 and "## Install" in md and "### Notes" in md and "- First item" in md
    assert "**Moon**" in md and "[more](https://example.org/more)" in md and "Copyright" not in md


def test_layout_tables_become_paragraphs_and_real_ones_get_a_header():
    md = "Intro\n\n| /bot review | \n\n| A long comment from a reviewer. | \n\nAfter\n\n| a | b |\n| c | d |\n"
    out = htmlmd.fix_tables(md)
    assert "/bot review\n\nA long comment from a reviewer.\n" in out and "| /bot" not in out
    assert "| a | b |\n|---|---|\n| c | d |" in out
    kept = "| x | y |\n|---|---|\n| 1 | 2 |"
    assert htmlmd.fix_tables(kept) == kept
    assert htmlmd.fix_tables("```\n| not | a table |\n```") == "```\n| not | a table |\n```"


def test_a_page_without_main_content_keeps_its_structure(monkeypatch):
    """Before: html2txt gave all of it on one line."""
    body = (b"<html><body><h2>Status</h2><ul><li>API: up</li><li>Web: down</li></ul>"
            b"<table><tr><td>a</td><td>1</td></tr><tr><td>b</td><td>2</td></tr></table>"
            b"<pre>x = 1\n\ny = 2</pre><script>var s = 1;</script><!-- a comment --><p>Bye</p></body></html>")
    text = htmlmd.plain(body)
    assert text.startswith("## Status\n\n- API: up\n- Web: down")
    assert "| a | 1 |\n|---|---|\n| b | 2 |" in text and "```\nx = 1\n\ny = 2\n```" in text and text.endswith("Bye")
    assert "var s" not in text and "comment" not in text
    monkeypatch.setattr(pages.trafilatura, "extract", lambda *a, **k: None)   # trafilatura found no main content
    md = convert(body)
    assert "## Status\n\n- API: up" in md and "| b | 2 |" in md


def test_heading_anchors_are_dropped():
    """Plan 30.8: Sphinx's `¶` and other permalinks after headings and definitions don't reach the markdown; code keeps them."""
    md = "\n".join([
        "# `shlex` — Simple lexical analysis[¶](https://docs.python.org#module-shlex)",
        'shlex.split(*s*)[¶](https://docs.python.org#shlex.split "Permalink to this definition")',
        "## Install [#](https://example.org/a#install)",
        "## Usage[](#usage)",
        "### Notes ¶",
        "## Links 🔗",
        "See [the guide](https://example.org/guide#install) and [link](#install).",
        "```python",
        'x = "[¶](#a)"  # ¶',
        "```",
    ])
    out = htmlmd.strip_anchors(md).split("\n")
    assert out[:6] == ["# `shlex` — Simple lexical analysis", "shlex.split(*s*)", "## Install", "## Usage", "### Notes", "## Links"]
    assert out[6] == "See [the guide](https://example.org/guide#install) and [link](#install)."
    assert out[8] == 'x = "[¶](#a)"  # ¶'


def test_sphinx_page_has_no_pilcrows():
    body = ("<!doctype html><html><head><title>Data Structures</title></head><body><div class='body'><section>"
            "<h1>5. Data Structures<a class='headerlink' href='#data-structures' title='Permalink to this headline'>¶</a></h1>"
            "<p>This chapter describes some things you've learned about already in more detail, and adds some new things as well.</p>"
            "<h2>5.1. More on Lists<a class='headerlink' href='#more-on-lists'>¶</a></h2>"
            "<p>The list data type has some more methods. Here are all of the methods of list objects, with words enough.</p>"
            "</section></div></body></html>").encode()
    text = convert(body)
    assert "¶" not in text
    assert "More on Lists" in text


def test_the_pages_description_is_kept(tmp_path):
    """webread.py's "About this page" line: the page's meta description, in the sidecar and the fetch result."""
    import json

    body = DOC.replace(b"<title>Guide to tides</title>", b'<title>Guide to tides</title><meta name="description" content="How the  Moon\nmoves the sea.">')
    f = SimpleNamespace(url="https://example.org/tides", content_type="text/html", body=body, charset="utf-8")
    p = pages.convert(f, "2026-10-21T10:00:00-04:00")
    assert p.description == "How the Moon moves the sea."
    side = json.loads(pages.save(tmp_path, p, f.url, f.url, "text/html").with_suffix(".md.json").read_text())
    assert side["description"] == "How the Moon moves the sea."
    assert pages.convert(SimpleNamespace(**{**f.__dict__, "body": DOC}), "x").description is None
