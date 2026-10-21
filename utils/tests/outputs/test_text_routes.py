"""Plan 24.3: /api/outputs/{id}/text, /search and /page/{n}.png."""

from __future__ import annotations

import io

import pytest
from PIL import Image

from utils.outputs import reading
from utils.tests.conftest import FIXTURES
from utils.tests.fixtures.docs.make import pdf

DOCS = FIXTURES / "docs"


async def up(client, name: str, data: bytes | None = None) -> dict:
    r = await client.post("/api/outputs/upload", params={"name": name}, content=data if data is not None else (DOCS / name).read_bytes())
    assert r.status_code == 201, r.text
    return r.json()


def long_pdf(n: int = 6) -> bytes:
    return pdf([f"Chapter {i + 1}\n" + "\n".join(f"Page {i + 1} line {k} about otters." for k in range(30)) for i in range(n)],
               [(f"Chapter {i + 1}", i) for i in range(n)])


async def test_text_paging_by_offset(client):
    o = await up(client, "long.pdf", long_pdf())
    first = (await client.get(f"/api/outputs/{o['id']}/text", params={"limit": 1000})).json()
    assert first["offset"] == 0 and first["pages"] == 6 and first["page_of_offset"] == 1 and not first["truncated"]
    assert first["text"].startswith("--- page 1 ---") and first["text"].endswith("\n")  # cut at a line end
    assert first["next_offset"] == len(first["text"]) and first["total_chars"] > 1000
    assert [x["title"] for x in first["outline"]] == [f"Chapter {i}" for i in range(1, 7)]
    assert first["tokens"] == (first["total_chars"] + 3) // 4
    # follow next_offset to the end: the windows join into the whole text
    parts, off = [first["text"]], first["next_offset"]
    while off is not None:
        w = (await client.get(f"/api/outputs/{o['id']}/text", params={"offset": off, "limit": 1000})).json()
        parts.append(w["text"])
        off = w["next_offset"]
    assert len("".join(parts)) == first["total_chars"]
    # the default limit and the cap
    assert len((await client.get(f"/api/outputs/{o['id']}/text")).json()["text"]) <= reading.LIMIT
    assert (await client.get(f"/api/outputs/{o['id']}/text", params={"limit": 48001})).status_code == 422


async def test_text_by_page_and_range(client):
    o = await up(client, "long.pdf", long_pdf())
    p3 = (await client.get(f"/api/outputs/{o['id']}/text", params={"page": 3})).json()
    assert p3["page_of_offset"] == 3 and p3["text"].startswith("\f--- page 3 ---\nChapter 3") and "page 4" not in p3["text"]
    r = (await client.get(f"/api/outputs/{o['id']}/text", params={"pages": "3-5"})).json()
    assert "Chapter 3" in r["text"] and "Chapter 5" in r["text"] and "Chapter 6" not in r["text"]
    assert r["next_offset"] is not None  # page 6 is still to come
    last = (await client.get(f"/api/outputs/{o['id']}/text", params={"pages": "6"})).json()
    assert last["next_offset"] is None
    for bad in ("7", "0", "5-3"):
        e = await client.get(f"/api/outputs/{o['id']}/text", params={"pages": bad})
        assert (e.status_code, e.json()["code"]) == (404, "no_page"), bad
    assert (await client.get(f"/api/outputs/{o['id']}/text", params={"pages": "x"})).json()["code"] == "invalid_request"
    md = await up(client, "readme.md")
    e = await client.get(f"/api/outputs/{md['id']}/text", params={"page": 1})
    assert e.json()["code"] == "no_page"
    w = (await client.get(f"/api/outputs/output:{md['id']}/text")).json()  # `output:<id>` works too
    assert w["pages"] == 0 and w["page_of_offset"] is None and w["outline"][0] == {"level": 1, "title": "Readme", "offset": 0, "line": 1}


async def test_search_words_phrase_and_regex(client):
    o = await up(client, "long.pdf", long_pdf())
    s = (await client.get(f"/api/outputs/{o['id']}/search", params={"q": "PAGE 4 line 7"})).json()
    assert s["total"] >= 1 and s["hits"][0]["page"] == 4
    hit = s["hits"][0]
    assert "Page 4 line 7 about otters." in hit["text"] and hit["text"].count("\n") == 2  # ±1 line of context
    s = (await client.get(f"/api/outputs/{o['id']}/search", params={"q": '"line 12 about"'})).json()
    assert s["total"] == 6 and [h["page"] for h in s["hits"]] == [1, 2, 3, 4, 5, 6]
    s = (await client.get(f"/api/outputs/{o['id']}/search", params={"q": '"line 12 about"', "limit": 2})).json()
    assert len(s["hits"]) == 2 and s["total"] == 6
    s = (await client.get(f"/api/outputs/{o['id']}/search", params={"q": r"/Page 2 line 2\d /"})).json()
    assert s["total"] == 10 and all(h["page"] == 2 for h in s["hits"])
    assert (await client.get(f"/api/outputs/{o['id']}/search", params={"q": "/page 2 LINE 29 /"})).json()["total"] == 0
    assert (await client.get(f"/api/outputs/{o['id']}/search", params={"q": "/page 2 LINE 29 /i"})).json()["total"] == 1
    assert (await client.get(f"/api/outputs/{o['id']}/search", params={"q": "/(/"})).json()["code"] == "invalid_request"
    assert (await client.get(f"/api/outputs/{o['id']}/search", params={"q": "zebra"})).json() == {"hits": [], "total": 0}


async def test_search_words_across_a_paragraph(client):
    o = await up(client, "notes.md", b"# Notes\n\nThe heron stood\nby the lake.\n\nA heron flew.\n")
    s = (await client.get(f"/api/outputs/{o['id']}/search", params={"q": "heron lake"})).json()
    assert s["total"] == 1 and s["hits"][0]["line"] == 3 and "page" not in s["hits"][0]


async def test_regex_search_times_out(client, monkeypatch):
    monkeypatch.setattr(reading, "REGEX_TIMEOUT_S", 0.3)
    o = await up(client, "slow.txt", ("a" * 40 + "!\n").encode())
    r = await client.get(f"/api/outputs/{o['id']}/search", params={"q": "/(a+)+$/"})
    assert (r.status_code, r.json()["code"]) == (422, "search_timeout")


async def test_a_capped_search_answers_through_the_route(client, monkeypatch):
    """Overnight 2026-10-21: word searches gained a cap and `capped: true`; the route's model forbids extra keys."""
    monkeypatch.setattr(reading, "MAX_MATCHES", 3)
    o = await up(client, "many.txt", "".join(f"quick line {i}\n" for i in range(10)).encode())
    r = await client.get(f"/api/outputs/{o['id']}/search", params={"q": "quick"})
    assert r.status_code == 200, r.text
    assert r.json()["capped"] is True and r.json()["total"] == 3


async def test_page_image(client, app):
    o = await up(client, "report.pdf")
    r = await client.get(f"/api/outputs/{o['id']}/page/2.png", params={"width": 300})
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    im = Image.open(io.BytesIO(r.content))
    assert im.size[0] == 300 and im.size[1] == pytest.approx(300 * 792 / 612, abs=2)
    cached = app.state.hub.outputs.dir / ".previews" / o["id"] / "p2-w300.png"
    assert cached.is_file()
    assert (await client.get(f"/api/outputs/{o['id']}/page/9.png")).json()["code"] == "no_page"
    md = await up(client, "readme.md")
    assert (await client.get(f"/api/outputs/{md['id']}/page/1.png")).status_code == 409
    # deleting the output removes its page images
    await client.delete(f"/api/outputs/{o['id']}")
    assert not cached.parent.exists()


async def test_errors_for_kinds_without_text(client):
    import io as _io

    b = _io.BytesIO()
    Image.new("RGB", (4, 4)).save(b, "PNG")
    o = await up(client, "pic.png", b.getvalue())
    for path in ("text", "search?q=x"):
        r = await client.get(f"/api/outputs/{o['id']}/{path}")
        assert (r.status_code, r.json()["code"]) == (409, "not_text"), path
    assert (await client.get("/api/outputs/nope/text")).json()["code"] == "output_not_found"
