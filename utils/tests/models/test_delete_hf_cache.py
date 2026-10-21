"""Deleting a model in the Hugging Face cache frees its weights, shared blobs included (hf_cache.py)."""

from __future__ import annotations

import hashlib
from pathlib import Path

from utils.tests.models.conftest import Models

HUB = "hf-cache/hub"


def _hex(s: str, n: int) -> str:
    return hashlib.sha256(s.encode()).hexdigest()[:n]


class Cache:
    """A fake `hf-cache/hub` laid out the way huggingface_hub 2.x writes it."""

    def __init__(self, m: Models) -> None:
        self.m = m
        self.hub = m.dir / HUB

    def shared(self, name: str, size: int) -> Path:
        """A payload in the cache-wide store `blobs/<xx>/<hash>` (the store marked as huggingface_hub marks it)."""
        (self.hub / "blobs").mkdir(parents=True, exist_ok=True)
        (self.hub / "blobs/.huggingface-shared-blobs").write_text("1\n")
        h = _hex(name, 64)
        return self.m.put(f"{HUB}/blobs/{h[:2]}/{h}", size)

    def repo(self, repo_id: str, files: dict[str, Path | int]) -> tuple[str, str]:
        """A repo at one revision: each file is a shared payload (linked through the repo's
        `blobs/<etag>`, listed in the payload's `.refs`) or a size for a per-repo blob."""
        base = f"{HUB}/models--{repo_id.replace('/', '--')}"
        rev = _hex(repo_id, 40)
        self.m.put(f"{base}/refs/main", rev.encode())
        snap = self.m.dir / base / "snapshots" / rev
        snap.mkdir(parents=True)
        for name, blob in files.items():
            etag = _hex(repo_id + name, 64)
            repo_blob = self.m.dir / base / "blobs" / etag
            if isinstance(blob, Path):
                repo_blob.parent.mkdir(parents=True, exist_ok=True)
                repo_blob.symlink_to(f"../../blobs/{blob.parent.name}/{blob.name}")
                with blob.with_name(blob.name + ".refs").open("a") as f:
                    f.write(f"{base.removeprefix(HUB + '/')}/blobs/{etag}\n")
            else:
                self.m.put(f"{base}/blobs/{etag}", blob)
            (snap / name).symlink_to(f"../../blobs/{etag}")
        return base, rev

    def entry(self, base: str, rev: str, names: list[str]) -> dict:
        files = [{"path": f"{base}/snapshots/{rev}/{n}"} for n in names] + [{"path": f"{base}/refs/main", "role": "ref"}]
        return {"format": "hf-dir", "kind": "llm", "path": base, "files": files}


async def test_shared_blob_freed_and_the_one_another_repo_uses_kept(root, client):
    m = Models(root)
    c = Cache(m)
    common, own = c.shared("tokenizer", 12), c.shared("weights", 40)
    a, a_rev = c.repo("org/a", {"model.safetensors": own, "tokenizer.json": common, "config.json": 5})
    b, b_rev = c.repo("org/b", {"tokenizer.json": common})
    m.write({"a": c.entry(a, a_rev, ["model.safetensors", "tokenizer.json", "config.json"]), "b": c.entry(b, b_rev, ["tokenizer.json"])})

    assert (await client.delete("/api/models/a?files=1")).status_code == 204
    assert not (m.dir / a).exists()
    assert not own.exists() and not own.with_name(own.name + ".refs").exists()  # the weights are freed
    assert common.exists() and common.with_name(common.name + ".refs").read_text() == f"{b.removeprefix(HUB + '/')}/blobs/{_hex('org/btokenizer.json', 64)}\n"
    assert (m.dir / b / "snapshots" / b_rev / "tokenizer.json").read_bytes() == common.read_bytes()
    assert list(m.read()["models"]) == ["b"]

    assert (await client.delete("/api/models/b?files=1")).status_code == 204
    assert not common.exists() and not (m.dir / b).exists()
    assert (c.hub / "blobs/.huggingface-shared-blobs").exists()  # the store itself stays


async def test_per_repo_blobs_still_deleted(root, client):
    m = Models(root)
    c = Cache(m)
    a, a_rev = c.repo("org/old", {"model.bin": 30, "config.json": 4})
    keep, keep_rev = c.repo("org/keep", {"model.bin": 8})
    m.write({"old": c.entry(a, a_rev, ["model.bin", "config.json"]), "keep": c.entry(keep, keep_rev, ["model.bin"])})
    assert (await client.delete("/api/models/old?files=1")).status_code == 204
    assert not (m.dir / a).exists()
    assert (m.dir / keep / "snapshots" / keep_rev / "model.bin").stat().st_size == 8


async def test_only_this_repo_even_when_another_has_the_same_revision(root, client):
    m = Models(root)
    c = Cache(m)
    a, rev = c.repo("org/a", {"model.bin": 10})
    twin = f"{HUB}/models--org--twin"  # a copy of the repo under another name, same commit hash
    m.put(f"{twin}/refs/main", rev.encode())
    m.put(f"{twin}/snapshots/{rev}/model.bin", 10)
    m.write({"a": c.entry(a, rev, ["model.bin"])})
    assert (await client.delete("/api/models/a?files=1")).status_code == 204
    assert not (m.dir / a).exists() and (m.dir / twin / "snapshots" / rev / "model.bin").exists()


async def test_a_repo_huggingface_hub_calls_corrupted_falls_back(root, client):
    m = Models(root)
    c = Cache(m)
    a, rev = c.repo("org/a", {"model.bin": 10, "config.json": 3})
    (m.dir / a / "blobs" / _hex("org/aconfig.json", 64)).unlink()  # a broken snapshot link
    m.write({"a": c.entry(a, rev, ["model.bin", "config.json"])})
    assert (await client.delete("/api/models/a?files=1")).status_code == 204
    assert not (m.dir / a).exists()


async def test_other_folders_are_not_treated_as_cache_repos(root, client):
    m = Models(root)
    m.put("hf-cache/hub/models--org--a/extra/w.bin", 4)
    m.put("hf-cache/hub/models--org--a/extra/notes.txt", 4)
    m.write({"x": {"path": "hf-cache/hub/models--org--a/extra", "files": [m.file("hf-cache/hub/models--org--a/extra/w.bin")]}})
    assert (await client.delete("/api/models/x?files=1")).status_code == 204
    assert sorted(p.name for p in (m.dir / "hf-cache/hub/models--org--a/extra").iterdir()) == ["notes.txt"]
