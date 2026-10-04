"""3.3 deliverable: `aihub models list | show | scan | verify` against a running hub."""

from __future__ import annotations

from utils.tests.models.conftest import Models
from utils.tests.services.test_new import run


def test_models_cli_end_to_end(root, hub_process):
    url = hub_process.url
    m = Models(root)
    m.put("llm/G/g-Q4.gguf", 4096)
    m.put("llm/G/mmproj-g.gguf", 100)
    m.put("vae/v.safetensors", 300)
    r = run("models", "list", root=root, url=url)
    assert (r.returncode, r.stdout.splitlines()[-1].split(" · ")[0]) == (0, "0 models")
    r = run("models", "scan", root=root, url=url)
    assert r.returncode == 0 and "llm/G" in r.stdout and "2 not registered" in r.stdout
    r = run("models", "scan", "--add", root=root, url=url)
    assert r.returncode == 0 and "added g-q4" in r.stdout and "added v" in r.stdout
    assert run("models", "scan", root=root, url=url).stdout.startswith("nothing new")
    r = run("models", "verify", "--all", root=root, url=url)
    assert r.returncode == 0 and "g-q4: ok" in r.stdout and "v: ok" in r.stdout, r.stdout + r.stderr
    r = run("models", "list", "--kind", "llm", root=root, url=url)
    assert "g-q4" in r.stdout and " v " not in r.stdout and "1 of 2 models" in r.stdout
    (m.dir / "vae/v.safetensors").write_bytes(b"x" * 300)  # same size, new content
    r = run("models", "verify", "v", root=root, url=url)
    assert r.returncode == 1 and "v: checksum_mismatch" in r.stdout and "Checksum mismatch" in r.stdout
    r = run("models", "show", "g-q4", root=root, url=url)
    assert "mmproj" in r.stdout and "verified" in r.stdout and "data/models/llm/G" in r.stdout
    r = run("models", "verify", "nope", root=root, url=url)
    assert r.returncode == 1 and 'No model "nope"' in r.stderr
    (m.dir / "llm/G/g-Q4.gguf").unlink()
    r = run("models", "list", "--problems", root=root, url=url)
    assert "g-q4: File not found: llm/G/g-Q4.gguf" in r.stdout and "partial" in r.stdout
