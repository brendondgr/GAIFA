"""4.4 delete: an output goes to outputs/.trash with its sidecar and preview; the trash is purged after 30 days."""

from __future__ import annotations

from datetime import date

from utils.outputs import trash
from utils.tests.outputs.conftest import drain, index


async def ids(client) -> dict[str, str]:
    return {o["title"]: o["id"] for o in (await client.get("/api/outputs")).json()["items"]}


async def test_delete_moves_a_file_output_with_its_companions(app, client, hub_tree):
    big = hub_tree.png("comfy/2026-10-04/120000-big.png", 2600, 1700)
    big.with_name(big.name + ".json").write_text('{"prompt": "fox"}')
    hub_tree.put("comfy/2026-10-04/120001-other.txt", "keep me")
    await index(app)
    o = await ids(client)
    assert (await client.get(f"/api/outputs/{o['big']}/preview")).status_code == 200  # the cached preview now exists
    assert (hub_tree.dir / "comfy/2026-10-04/.120000-big.png.preview.jpg").exists()
    sub = app.state.hub.bus.subscribe()
    r = await client.delete(f"/api/outputs/{o['big']}")
    assert r.status_code == 204
    day = hub_tree.dir / ".trash" / date.today().isoformat() / "comfy/2026-10-04"
    assert sorted(p.name for p in day.iterdir()) == [".120000-big.png.preview.jpg", "120000-big.png", "120000-big.png.json"]
    assert sorted(p.name for p in (hub_tree.dir / "comfy/2026-10-04").iterdir()) == ["120001-other.txt"]
    events = drain(sub)
    assert {"type": "output_deleted", "id": o["big"]} in events
    assert any(e["type"] == "activity" and e["item"]["text"] == 'Moved "big" to the outputs trash' for e in events)
    assert (await client.get(f"/api/outputs/{o['big']}")).status_code == 404
    assert (await client.delete(f"/api/outputs/{o['big']}")).json()["code"] == "output_not_found"
    await index(app)  # the trash is never indexed
    assert list(await ids(client)) == ["other"]


async def test_delete_a_folder_output_and_the_same_path_twice(app, client, hub_tree):
    hub_tree.folder("gen3d/2026-10-04/j1-fox", {"mesh.glb": 9, "parts/p.glb": 2}, title="fox")
    await index(app)
    assert (await client.delete(f"/api/outputs/{(await ids(client))['fox']}")).status_code == 204
    hub_tree.folder("gen3d/2026-10-04/j1-fox", {"mesh.glb": 7}, title="fox")  # made again, deleted again
    await index(app)
    assert (await client.delete(f"/api/outputs/{(await ids(client))['fox']}")).status_code == 204
    t = hub_tree.dir / ".trash" / date.today().isoformat()
    assert (t / "gen3d/2026-10-04/j1-fox/parts/p.glb").exists()
    assert (t / "2/gen3d/2026-10-04/j1-fox/mesh.glb").stat().st_size == 7
    assert not (hub_tree.dir / "gen3d/2026-10-04/j1-fox").exists()


async def test_stem_sidecar_shared_by_two_files_stays(app, client, hub_tree):
    hub_tree.put("svc/2026-10-04/x.wav", 3)
    hub_tree.put("svc/2026-10-04/x.png", 3)
    hub_tree.put("svc/2026-10-04/x.json", '{"prompt": "both"}')
    await index(app)
    wav = next(o for o in (await client.get("/api/outputs")).json()["items"] if o["kind"] == "audio")
    await client.delete(f"/api/outputs/{wav['id']}")
    assert sorted(p.name for p in (hub_tree.dir / "svc/2026-10-04").iterdir()) == ["x.json", "x.png"]


async def test_a_file_already_gone_just_leaves_the_index(app, client, hub_tree):
    p = hub_tree.put("svc/2026-10-04/a.txt", "a")
    await index(app)
    p.unlink()
    assert (await client.delete(f"/api/outputs/{(await ids(client))['a']}")).status_code == 204
    assert not (hub_tree.dir / ".trash").exists()


async def test_refuses_outside_outputs(app, client, hub_tree, tmp_path_factory):
    elsewhere = tmp_path_factory.mktemp("elsewhere")
    (elsewhere / "2026-10-04").mkdir()
    (elsewhere / "2026-10-04/a.txt").write_text("a")
    (hub_tree.dir / "linked").symlink_to(elsewhere)
    await index(app)
    r = await client.delete(f"/api/outputs/{(await ids(client))['a']}")
    assert (r.status_code, r.json()["code"]) == (409, "output_not_deletable")
    assert (elsewhere / "2026-10-04/a.txt").exists()
    assert (await client.get("/api/outputs")).json()["totals"]["count"] == 1


def test_purge(tmp_path):
    out = tmp_path / "outputs"
    for d in ("2026-08-01", "2026-09-04", "2026-09-05", "2026-10-04", "not-a-date"):
        (out / ".trash" / d / "svc").mkdir(parents=True)
        (out / ".trash" / d / "svc" / "f.txt").write_text("x")
    assert trash.purge(out, today=date(2026, 10, 5)) == 2  # older than 30 days: before 2026-09-05
    assert sorted(p.name for p in (out / ".trash").iterdir()) == ["2026-09-05", "2026-10-04", "not-a-date"]
    assert trash.purge(tmp_path / "nothing-here") == 0
