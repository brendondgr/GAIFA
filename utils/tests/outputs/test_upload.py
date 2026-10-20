"""Chat uploads (plan chat-uploads U.4): a file sent to POST /api/outputs/upload becomes an output."""

from __future__ import annotations

import io
import json

import pytest
from PIL import Image

from utils.outputs import upload
from utils.tests.conftest import FIXTURES


def png(w: int = 8, h: int = 6) -> bytes:
    b = io.BytesIO()
    Image.new("RGB", (w, h), (200, 30, 30)).save(b, "PNG")
    return b.getvalue()


async def test_an_upload_becomes_an_output(app, client):
    r = await client.post("/api/outputs/upload", params={"name": "My Cat (1).PNG"}, content=png(), headers={"content-type": "image/png"})
    assert r.status_code == 201
    o = r.json()
    assert o["kind"] == "image" and o["service"] == "uploads" and o["title"] == "My Cat (1).PNG"
    assert (o["dims"]["w"], o["dims"]["h"]) == (8, 6)
    assert o["path"].startswith("outputs/uploads/") and o["path"].endswith("-my-cat-1.png")
    side = app.state.hub.outputs.dir / (o["path"].removeprefix("outputs/") + ".json")
    assert json.loads(side.read_text())["source"] == {"service": "upload"}
    assert (await client.get(f"/api/outputs/{o['id']}")).json()["id"] == o["id"]
    file = await client.get(f"/api/outputs/{o['id']}/file")
    assert file.status_code == 200 and file.content == png()
    # the same name again in the same second gets its own file
    again = (await client.post("/api/outputs/upload", params={"name": "My Cat (1).PNG"}, content=png(4, 4))).json()
    assert again["id"] != o["id"] and (again["dims"]["w"], again["dims"]["h"]) == (4, 4)


async def test_upload_errors_use_the_envelope(app, client, monkeypatch):
    r = await client.post("/api/outputs/upload", params={"name": "notes.exe"}, content=b"x")
    assert r.status_code == 415 and r.json()["code"] == "upload_type"
    r = await client.post("/api/outputs/upload", params={"name": "empty.png"}, content=b"")
    assert r.status_code == 400 and r.json()["code"] == "upload_empty"
    monkeypatch.setattr(upload, "MAX_BYTES", 10)
    r = await client.post("/api/outputs/upload", params={"name": "big.png"}, content=png())
    assert r.status_code == 413 and r.json()["code"] == "upload_too_large"
    assert not (app.state.hub.outputs.dir / "uploads").exists() or not any((app.state.hub.outputs.dir / "uploads").rglob("big*"))


# ---- plan 24.1: text and documents ----

DOCS = FIXTURES / "docs"


@pytest.mark.parametrize("name,kind,subtype", [
    ("report.pdf", "document", "pdf"), ("notes.docx", "document", "docx"), ("book.epub", "document", "epub"),
    ("analysis.ipynb", "text", "notebook"), ("people.csv", "text", "data:csv"), ("hello.py", "text", "code:python"),
    ("readme.md", "text", "markdown"),
])
async def test_documents_and_text_upload(client, name, kind, subtype):
    data = (DOCS / name).read_bytes()
    r = await client.post("/api/outputs/upload", params={"name": name}, content=data)
    assert r.status_code == 201, r.text
    o = r.json()
    assert (o["kind"], o["subtype"]) == (kind, subtype)
    assert o["path"].endswith("." + name.rsplit(".", 1)[1])
    f = await client.get(o["url"])
    assert f.content == data and f.headers["x-content-type-options"] == "nosniff"
    listed = (await client.get("/api/outputs", params={"kind": kind})).json()
    assert o["id"] in [x["id"] for x in listed["items"]]


async def test_text_must_be_utf8_or_utf16_with_a_bom(client):
    r = await client.post("/api/outputs/upload", params={"name": "notes.txt"}, content=png())
    assert r.status_code == 415 and r.json()["code"] == "upload_encoding"
    r = await client.post("/api/outputs/upload", params={"name": "nul.txt"}, content=b"abc\x00def")
    assert r.json()["code"] == "upload_encoding"
    r = await client.post("/api/outputs/upload", params={"name": "wide.txt"}, content="hello".encode("utf-16-le"))
    assert r.status_code == 415  # UTF-16 without a BOM
    r = await client.post("/api/outputs/upload", params={"name": "wide.txt"}, content=b"\xff\xfe" + "hé".encode("utf-16-le"))
    assert r.status_code == 201 and r.json()["kind"] == "text"


async def test_html_is_served_as_plain_text_and_env_example_keeps_its_extension(client):
    o = (await client.post("/api/outputs/upload", params={"name": "garden.html"}, content=(DOCS / "garden.html").read_bytes())).json()
    assert o["subtype"] == "web:html"
    assert (await client.get(o["url"])).headers["content-type"].startswith("text/plain")
    o = (await client.post("/api/outputs/upload", params={"name": ".env.example"}, content=b"KEY=1\n")).json()
    assert o["path"].endswith(".env.example") and o["subtype"] == "config:env"


def test_uploads_of_one_name_at_once_get_their_own_files(tmp_path):
    """Three uploads of the same name in the same second, at the same time (the eval's runs): no clash."""
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(8) as ex:
        rels = list(ex.map(lambda i: upload.save_upload(tmp_path, "report.pdf", b"%PDF-" + bytes([i]), now=1_790_000_000), range(8)))
    assert len(set(rels)) == 8
    assert sorted((tmp_path / r).read_bytes()[-1] for r in rels) == list(range(8))
