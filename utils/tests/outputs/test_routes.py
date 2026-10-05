"""4.4: the output routes: paging, totals, filters, Range, and the traversal guard."""

from __future__ import annotations

from utils.tests.outputs.conftest import index


async def test_paging_is_stable_across_equal_timestamps(app, client, hub_tree):
    for i in range(100):
        hub_tree.put(f"tts/2026-10-04/{i:03d}.txt", "x", sidecar={"created_ts": 1_700_000_000 + i})
    for i in range(50):  # same created_ts: ordered by id
        hub_tree.put(f"comfy/2026-10-04/same-{i:02d}.txt", "x", sidecar={"created_ts": 1_699_000_000.25})
    await index(app)
    seen, cursor, pages = [], None, 0
    while True:
        r = (await client.get("/api/outputs", params={"limit": 60, **({"cursor": cursor} if cursor else {})})).json()
        seen += r["items"]
        pages += 1
        assert r["totals"]["count"] == 150
        cursor = r["next_cursor"]
        if not cursor:
            break
    assert pages == 3 and len(seen) == 150 and len({o["id"] for o in seen}) == 150
    keys = [(o["created_ts"], o["id"]) for o in seen]
    assert keys == sorted(keys, reverse=True)
    assert seen[0]["title"] == "099"


async def test_totals_and_filters(app, client, hub_tree):
    hub_tree.put("tts/2026-10-04/100000-good-morning.wav", 100, sidecar={"prompt": "Good morning, everyone", "created_ts": 1000})
    hub_tree.put("tts/2026-10-04/100001-evening.wav", 50, sidecar={"created_ts": 2000})
    hub_tree.png("comfy/2026-10-04/fox.png")
    hub_tree.put("comfy/2026-10-04/notes.txt", "a misty pine forest", sidecar={"created_ts": 3000})
    await index(app)
    r = (await client.get("/api/outputs")).json()
    assert r["totals"]["count"] == 4 and r["totals"]["by_kind"] == {"audio": 2, "image": 1, "text": 1}
    assert r["totals"]["by_service"] == {"tts": 2, "comfy": 2}
    r = (await client.get("/api/outputs", params={"service": "tts"})).json()
    assert r["totals"]["count"] == 2 and r["totals"]["size_bytes"] == 150
    assert r["totals"]["by_kind"] == {"audio": 2}  # kinds within the service filter
    assert r["totals"]["by_service"] == {"tts": 2, "comfy": 2}  # services ignore the service filter
    r = (await client.get("/api/outputs", params={"kind": "audio,text"})).json()
    assert r["totals"]["count"] == 3 and r["totals"]["by_kind"] == {"audio": 2, "image": 1, "text": 1}
    assert r["totals"]["by_service"] == {"tts": 2, "comfy": 1}
    assert [o["title"] for o in (await client.get("/api/outputs", params={"q": "MORNING everyone"})).json()["items"]] == ["good morning"]
    assert (await client.get("/api/outputs", params={"q": "100_0"})).json()["totals"]["count"] == 0  # LIKE wildcards are literal
    assert (await client.get("/api/outputs", params={"q": "100%"})).json()["totals"]["count"] == 0
    r = (await client.get("/api/outputs", params={"from": 1500, "to": 3000})).json()
    assert sorted(o["title"] for o in r["items"]) == ["evening", "notes"]


async def test_bad_queries(client):
    for params, frag in (({"kind": "audio,bogus"}, "kind"), ({"cursor": "nope"}, "cursor"), ({"limit": 501}, "limit")):
        r = await client.get("/api/outputs", params=params)
        assert r.status_code == 422 and r.json()["code"] == "invalid_request" and frag in r.json()["detail"]
    r = await client.get("/api/outputs/0123456789ab")
    assert (r.status_code, r.json()["code"]) == (404, "output_not_found")


async def test_get_and_file_with_range(app, client, hub_tree):
    data = bytes(range(256)) * 40
    hub_tree.put("tts/2026-10-04/120000-clip.wav", data, sidecar={"voice": "hope"})
    await index(app)
    o = (await client.get("/api/outputs")).json()["items"][0]
    assert (await client.get(f"/api/outputs/{o['id']}")).json() == o
    assert o["meta"] == {"voice": "hope"} and "dims" not in o
    r = await client.get(o["url"])
    assert r.status_code == 200 and r.content == data and r.headers["content-type"] == "audio/wav"
    assert r.headers["accept-ranges"] == "bytes" and r.headers["cache-control"] == "no-cache"
    r = await client.get(o["url"], headers={"Range": "bytes=100-199"})
    assert r.status_code == 206 and r.content == data[100:200] and r.headers["content-range"] == f"bytes 100-199/{len(data)}"
    r = await client.get(o["url"], headers={"Range": "bytes=-16"})
    assert r.status_code == 206 and r.content == data[-16:]
    assert (await client.get(o["url"], headers={"Range": f"bytes={len(data)}-"})).status_code == 416
    r = await client.head(o["url"])
    assert r.status_code == 200 and int(r.headers["content-length"]) == len(data)
    (hub_tree.dir / "tts/2026-10-04/120000-clip.wav").unlink()
    r = await client.get(o["url"])
    assert (r.status_code, r.json()["code"]) == (404, "output_not_found")


async def test_folder_files_and_the_traversal_guard(app, client, hub_tree, root):
    hub_tree.folder("gen3d/2026-10-04/j1-fox", {"mesh.glb": b"glTF-mesh", "parts/part_00.glb": b"glTF-part", "preview.png": 3})
    hub_tree.put("tts/2026-10-04/a.txt", "a")
    (root / "secret.txt").write_text("TOP-SECRET-CONTENT")
    await index(app)
    items = {o["kind"]: o for o in (await client.get("/api/outputs")).json()["items"]}
    fox, txt = items["model3d"], items["text"]
    assert [f["path"] for f in fox["files"]] == [
        "outputs/gen3d/2026-10-04/j1-fox/mesh.glb", "outputs/gen3d/2026-10-04/j1-fox/preview.png", "outputs/gen3d/2026-10-04/j1-fox/parts/part_00.glb"]
    r = await client.get(f"/api/outputs/{fox['id']}/file")
    assert r.content == b"glTF-mesh" and r.headers["content-type"] == "model/gltf-binary"
    r = await client.get(f"/api/outputs/{fox['id']}/files/parts/part_00.glb")
    assert r.status_code == 200 and r.content == b"glTF-part"
    for bad in ("../../../secret.txt", "..%2F..%2F..%2Fsecret.txt", "output.json", "parts/../../j1-fox/mesh.glb", "/etc/passwd", "nope.glb"):
        r = await client.get(f"/api/outputs/{fox['id']}/files/{bad}")
        assert r.status_code == 404, bad
        assert b"TOP-SECRET-CONTENT" not in r.content
    assert (await client.get(f"/api/outputs/{txt['id']}/files/a.txt")).status_code == 404  # a file output has no inner files


async def test_openapi_documents_the_output_routes(client):
    paths = (await client.get("/api/openapi.json")).json()["paths"]
    assert {"/api/outputs", "/api/outputs/{output_id}", "/api/outputs/{output_id}/file",
            "/api/outputs/{output_id}/files/{path}", "/api/outputs/{output_id}/preview"} <= set(paths)
    assert set(paths["/api/outputs/{output_id}"]) == {"get", "delete"}
