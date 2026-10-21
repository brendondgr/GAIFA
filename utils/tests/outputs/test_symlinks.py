"""Symlinks out of outputs/ are never indexed or served (found overnight 2026-10-21: a link planted by a mod
or a custom node made /file, /files and /text serve whatever it pointed at, a private key included)."""

from __future__ import annotations

import os

from utils.tests.outputs.conftest import index


async def test_links_out_of_outputs_are_not_indexed(app, client, hub_tree, root):
    secret = root / "secret"
    secret.mkdir()
    (secret / "id_ed25519").write_text("PRIVATE-KEY")
    hub_tree.put("tts/2026-10-04/a.txt", "a")
    day = hub_tree.dir / "workspace" / "2026-10-04"
    day.mkdir(parents=True)
    os.symlink(secret / "id_ed25519", day / "x.txt")                   # a file link out
    os.symlink(secret, hub_tree.dir / "workspace" / "linked")           # a folder link out
    os.symlink(hub_tree.dir / "tts" / "2026-10-04" / "a.txt", day / "alias.txt")   # a link that stays inside
    hub_tree.folder("gen3d/2026-10-04/j1-fox", {"mesh.glb": b"glTF-mesh"})
    os.symlink(secret / "id_ed25519", hub_tree.dir / "gen3d" / "2026-10-04" / "j1-fox" / "k.txt")
    await index(app)
    items = (await client.get("/api/outputs")).json()["items"]
    titles = sorted(o["title"] for o in items)
    assert "x" not in titles and "id_ed25519" not in titles and "alias" in titles
    fox = next(o for o in items if o["kind"] == "model3d")
    assert [f["path"].rsplit("/", 1)[-1] for f in fox["files"]] == ["mesh.glb"]
    r = await client.get(f"/api/outputs/{fox['id']}/files/k.txt")
    assert r.status_code == 404 and b"PRIVATE-KEY" not in r.content


async def test_a_file_swapped_for_a_link_after_indexing_is_not_served(app, client, hub_tree, root):
    (root / "secret.txt").write_text("PRIVATE-KEY")
    p = hub_tree.put("tts/2026-10-04/a.txt", "a")
    await index(app)
    oid = (await client.get("/api/outputs")).json()["items"][0]["id"]
    p.unlink()
    os.symlink(root / "secret.txt", p)
    for route in ("file", "text"):
        r = await client.get(f"/api/outputs/{oid}/{route}")
        assert r.status_code == 404 and b"PRIVATE-KEY" not in r.content, route
