"""Chat uploads (plan chat-uploads U.4): a file sent to POST /api/outputs/upload becomes an output."""

from __future__ import annotations

import io
import json

from PIL import Image

from utils.outputs import upload


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
