"""4.1: which files are outputs, and what gets recorded for each."""

from __future__ import annotations

import hashlib
import json
import os

import pytest

from utils.outputs.describe import describe, title_from
from utils.outputs.entries import scope_for, walk
from utils.tests.outputs.conftest import drain, needs_ffmpeg, ts


def test_walk_rules(tree):
    t = ts("2026-10-04 09:00:00")
    tree.put("tts/2026-10-04/143012-good-morning.wav", 10, sidecar={"title": "Good morning"})
    tree.put("tts/2026-10-04/143013-next.wav.part", 10)  # still being written
    tree.put("tts/2026-10-04/.143012-good-morning.wav.preview.jpg", 10)  # the hub's own preview
    tree.put("tts/2026-10-04/150000-clip.mp3", 10)
    tree.put("tts/2026-10-04/150000-clip.json", "{}")  # a <stem>.json sidecar
    tree.put("tts/2026-10-04/notes.json", "{}")  # a JSON output (nothing shares its stem)
    tree.put("tts/saved/my-voice-demo.wav", 10, mtime=t)  # outside a date folder
    tree.put("comfy/2026-10-04/video/ComfyUI_00001_.mp4", 10)  # a mod's own subfolder
    tree.folder("gen3d/2026-10-04/j1-fox", {"mesh.glb": 5, "preview.png": 3, "parts/part_00.glb": 2})
    tree.folder("gen3d/2026-10-04/j2-chair", {"mesh.glb": 5}, complete=False)  # in progress
    tree.put("gen3d/2026-10-04/j3-broken/output.json", "{not json")
    tree.put("gen3d/2026-10-04/j3-broken/mesh.glb", 5)
    tree.put("stray.wav", 10)  # directly in outputs/: no service
    tree.put(".trash/2026-10-01/tts/old.wav", 10)
    found = walk(tree.dir)
    assert sorted(found) == [
        "comfy/2026-10-04/video/ComfyUI_00001_.mp4",
        "gen3d/2026-10-04/j1-fox",
        "tts/2026-10-04/143012-good-morning.wav",
        "tts/2026-10-04/150000-clip.mp3",
        "tts/2026-10-04/notes.json",
        "tts/saved/my-voice-demo.wav",
    ]
    f = found["tts/2026-10-04/143012-good-morning.wav"]
    assert f.service == "tts" and f.sidecar == "tts/2026-10-04/143012-good-morning.wav.json" and str(f.day) == "2026-10-04"
    assert found["tts/2026-10-04/150000-clip.mp3"].sidecar == "tts/2026-10-04/150000-clip.json"
    assert found["tts/saved/my-voice-demo.wav"].day is None
    fox = found["gen3d/2026-10-04/j1-fox"]
    assert fox.is_dir and sorted(r for r, _, _ in fox.files) == [
        "gen3d/2026-10-04/j1-fox/mesh.glb", "gen3d/2026-10-04/j1-fox/parts/part_00.glb", "gen3d/2026-10-04/j1-fox/preview.png"]
    # a scope sees only its folder
    assert sorted(walk(tree.dir, "tts/2026-10-04")) == ["tts/2026-10-04/143012-good-morning.wav", "tts/2026-10-04/150000-clip.mp3", "tts/2026-10-04/notes.json"]
    assert walk(tree.dir, "nope") == {} and walk(tree.dir, ".trash") == {}


def test_sig_changes_with_the_file_or_its_sidecar(tree):
    p = tree.put("tts/2026-10-04/a.wav", 10)
    s1 = walk(tree.dir)["tts/2026-10-04/a.wav"].sig
    p.with_name("a.wav.json").write_text('{"title": "A"}')
    s2 = walk(tree.dir)["tts/2026-10-04/a.wav"].sig
    p.write_bytes(b"\0" * 11)
    s3 = walk(tree.dir)["tts/2026-10-04/a.wav"].sig
    assert len({s1, s2, s3}) == 3


def test_symlink_loops_are_walked_once(tree):
    tree.put("svc/a/x.txt", "hi")
    (tree.dir / "svc/a/loop").symlink_to(tree.dir / "svc")
    assert sorted(walk(tree.dir)) == ["svc/a/x.txt"]


def test_scope_for(tree):
    d = tree.dir
    assert scope_for(d, d / "tts/2026-10-04/x.wav") == "tts/2026-10-04"
    assert scope_for(d, d / "tts/2026-10-04") == "tts/2026-10-04"
    assert scope_for(d, d / "gen3d/2026-10-04/job/parts/p.glb") == "gen3d/2026-10-04"
    assert scope_for(d, d / "tts/saved/x.wav") == "tts"
    assert scope_for(d, d / "tts") == "tts"
    assert scope_for(d, d) == ""
    assert scope_for(d, d / "tts/2026-10-04/x.wav.part") is None
    assert scope_for(d, d / "tts/2026-10-04/.x.wav.preview.jpg") is None
    assert scope_for(d, d / ".trash/2026-10-04/tts/x.wav") is None
    assert scope_for(d, d.parent / "elsewhere") is None


def test_titles():
    assert title_from("143012-good-morning.wav", False) == "good morning"
    assert title_from("ComfyUI_00012_.png", False) == "ComfyUI 00012"
    assert title_from("low-poly-fox", True) == "low poly fox"
    assert title_from("v1.2-final", True) == "v1.2 final"
    assert title_from(".wav", False) == ".wav"


def one(tree, rel: str) -> dict:
    found = walk(tree.dir)
    row = describe(tree.dir, found[rel])
    assert row is not None
    row["meta"], row["files"] = json.loads(row["meta"]), json.loads(row["files"])
    return row


def test_file_output_row(tree):
    tree.wav("tts/2026-10-04/143012-good-morning.wav", seconds=1.5, sidecar={
        "title": "Good morning", "prompt": "Good morning, everyone.", "model": "breeze-tts-2", "voice": "brendon",
        "seed": 1234, "params": {"speed": 1.0}, "complete": True, "source": {"service": "tts"}})
    r = one(tree, "tts/2026-10-04/143012-good-morning.wav")
    assert r["id"] == hashlib.sha1(b"tts/2026-10-04/143012-good-morning.wav").hexdigest()[:12]
    assert (r["service"], r["kind"], r["title"], r["is_dir"]) == ("tts", "audio", "Good morning", 0)
    assert r["created_ts"] == ts("2026-10-04 14:30:12")  # the date folder + the HHMMSS prefix
    assert r["duration_s"] == 1.5 and r["preview"] is None and r["main"] == r["path"]
    assert r["meta"] == {"prompt": "Good morning, everyone.", "model": "breeze-tts-2", "voice": "brendon", "seed": 1234,
                         "params": {"speed": 1.0}, "source": {"service": "tts"}}
    assert r["files"] == [{"path": "tts/2026-10-04/143012-good-morning.wav", "kind": "audio", "size_bytes": r["size_bytes"]}]
    assert "good morning, everyone." in r["search"] and "143012-good-morning.wav" in r["search"]


def test_created_without_a_time_prefix(tree):
    same_day = ts("2026-10-04 08:15:00")
    tree.put("svc/2026-10-04/a.txt", "x", mtime=same_day)
    tree.put("svc/2026-10-04/b.txt", "x", mtime=ts("2026-10-09 17:45:30"))  # copied in later
    tree.put("svc/loose.txt", "x", mtime=same_day)
    tree.put("svc/2026-10-04/c.txt", "x", mtime=same_day, sidecar={"created_ts": 1700000000.5})
    assert one(tree, "svc/2026-10-04/a.txt")["created_ts"] == same_day
    assert one(tree, "svc/2026-10-04/b.txt")["created_ts"] == ts("2026-10-04 17:45:30")  # the folder's date wins
    assert one(tree, "svc/loose.txt")["created_ts"] == same_day
    assert one(tree, "svc/2026-10-04/c.txt")["created_ts"] == 1700000000.5


def test_kind_title_and_excerpt(tree):
    tree.put("svc/2026-10-04/120000-notes.md", "# Heading\n\nSome notes " + "z" * 600)
    tree.put("svc/2026-10-04/120001-data.bin", 5, sidecar={"kind": "archive", "title": "  "})
    tree.put("svc/2026-10-04/120002-x.wav", 5, sidecar={"kind": "nonsense"})
    tree.put("svc/2026-10-04/120003-said.txt", "words", sidecar={"prompt": "the prompt"})
    md = one(tree, "svc/2026-10-04/120000-notes.md")
    assert md["kind"] == "text" and md["title"] == "notes"
    assert md["meta"]["excerpt"].startswith("# Heading\n\nSome notes") and md["meta"]["excerpt"].endswith("…")
    other = one(tree, "svc/2026-10-04/120001-data.bin")
    assert other["kind"] == "archive" and other["title"] == "data"
    assert one(tree, "svc/2026-10-04/120002-x.wav")["kind"] == "audio"  # an unknown kind is ignored
    assert "excerpt" not in one(tree, "svc/2026-10-04/120003-said.txt")["meta"]  # the card shows the prompt


def test_folder_output_row(tree):
    tree.folder("gen3d/2026-10-04/101500-low-poly-fox", {
        "preview.png": 30, "mesh.glb": 100, "rigged.glb": 120, "parts/part_00_base.glb": 10, "parts/part_01_body.glb": 11,
        "audio.wav": 5, ".hidden": 1, "tmp.glb.part": 9,
    }, title="low-poly fox", prompt="low-poly fox", seed=7)
    r = one(tree, "gen3d/2026-10-04/101500-low-poly-fox")
    assert (r["kind"], r["title"], r["is_dir"]) == ("model3d", "low-poly fox", 1)
    assert r["main"] == "gen3d/2026-10-04/101500-low-poly-fox/mesh.glb"  # model3d first, top level first, then by name
    assert r["preview"] == "gen3d/2026-10-04/101500-low-poly-fox/preview.png"
    assert r["size_bytes"] == 30 + 100 + 120 + 10 + 11 + 5
    assert r["created_ts"] == ts("2026-10-04 10:15:00")
    roles = {f["path"].rsplit("/", 1)[-1]: f.get("role") for f in r["files"]}
    assert roles == {"audio.wav": None, "mesh.glb": "main", "preview.png": "preview", "rigged.glb": None,
                     "part_00_base.glb": "part", "part_01_body.glb": "part"}
    assert r["meta"] == {"prompt": "low-poly fox", "seed": 7}


def test_folder_main_from_the_sidecar_and_fallbacks(tree):
    tree.folder("gen3d/2026-10-04/a", {"mesh.glb": 1, "rigged.glb": 1}, main="rigged.glb")
    tree.folder("gen3d/2026-10-04/b", {"mesh.glb": 1}, main="../../escape.glb")  # ignored
    tree.folder("svc/2026-10-04/c", {"z.wav": 1, "b.png": 1})  # image beats audio
    tree.folder("svc/2026-10-04/d", {"readme.txt": 1, "log.csv": 1})  # none of the media kinds: the first file
    tree.folder("svc/2026-10-04/e", {})  # nothing in it
    assert one(tree, "gen3d/2026-10-04/a")["main"].endswith("/rigged.glb")
    assert one(tree, "gen3d/2026-10-04/b")["main"].endswith("/mesh.glb")
    c = one(tree, "svc/2026-10-04/c")
    assert c["main"].endswith("/b.png") and c["kind"] == "image"
    assert one(tree, "svc/2026-10-04/d")["main"].endswith("/log.csv")
    e = one(tree, "svc/2026-10-04/e")
    assert e["main"] is None and e["kind"] == "other" and e["files"] == []


def test_images(tree):
    tree.png("comfy/2026-10-04/small.png", 64, 48)
    tree.png("comfy/2026-10-04/big.png", 2600, 1600)  # 4.16 MP
    tree.put("comfy/2026-10-04/broken.png", b"not a png")
    small = one(tree, "comfy/2026-10-04/small.png")
    assert (small["width"], small["height"]) == (64, 48) and small["preview"] == small["path"]  # the image itself
    big = one(tree, "comfy/2026-10-04/big.png")
    assert (big["width"], big["height"]) == (2600, 1600) and big["preview"] == "comfy/2026-10-04/.big.png.preview.jpg"
    broken = one(tree, "comfy/2026-10-04/broken.png")
    assert broken["width"] is None and broken["preview"] == broken["path"]


@needs_ffmpeg
def test_media_via_ffprobe(tree):
    tree.float_wav("tts/2026-10-04/float.wav", seconds=2.0)
    tree.mp4("comfy/2026-10-04/clip.mp4", seconds=2.0, size="320x240")
    assert one(tree, "tts/2026-10-04/float.wav")["duration_s"] == 2.0
    v = one(tree, "comfy/2026-10-04/clip.mp4")
    assert (v["kind"], v["width"], v["height"]) == ("video", 320, 240)
    assert v["duration_s"] == pytest.approx(2.0, abs=0.15) and v["preview"] == "comfy/2026-10-04/.clip.mp4.preview.jpg"


def test_vanished_before_describe(tree):
    p = tree.put("svc/a.txt", "x")
    f = walk(tree.dir)["svc/a.txt"]
    os.unlink(p)
    assert describe(tree.dir, f) is None


async def test_sync_upserts_and_removes(outs, tree, bus):
    tree.put("svc/2026-10-04/a.txt", "a")
    tree.put("svc/2026-10-04/b.txt", "b")
    sub = bus.subscribe()
    assert await outs.sync() is False
    page = await outs.list()
    assert page["totals"]["count"] == 2
    a = next(o for o in page["items"] if o["title"] == "a")
    assert a["path"] == "outputs/svc/2026-10-04/a.txt" and a["url"] == f"/api/outputs/{a['id']}/file"
    assert a["files"] == [{"path": "outputs/svc/2026-10-04/a.txt", "kind": "text", "size_bytes": 1}]
    assert [e["type"] for e in drain(sub) if e["type"].startswith("output")] == ["output", "output"]
    await outs.sync()  # nothing changed: nothing written, nothing published
    assert [e for e in drain(sub) if e["type"].startswith("output")] == []
    (tree.dir / "svc/2026-10-04/a.txt").write_text("aa")
    os.unlink(tree.dir / "svc/2026-10-04/b.txt")
    await outs.sync("svc/2026-10-04")
    ev = [e for e in drain(sub) if e["type"].startswith("output")]
    assert [e["type"] for e in ev] == ["output", "output_deleted"]
    assert ev[0]["output"]["size_bytes"] == 2
    assert (await outs.list())["totals"] == {"count": 1, "size_bytes": 2, "by_kind": {"text": 1}, "by_service": {"svc": 1}}

