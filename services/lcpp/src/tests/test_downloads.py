"""Hugging Face downloads against a fake Hub (httpx.MockTransport): input
parsing, repo classification, and the resolve → download → catalog flow."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from lcpp.daemon.app import create_app
from lcpp.downloads import gguf_choices, parse_input, suggest_dir

GGUF_REPO = "ewin-reg/Mini-1B-GGUF"
LINK = f"https://huggingface.co/{GGUF_REPO}/resolve/main/Mini-1B.Q4_K_M.gguf?download=true"


def blob(name: str, size: int) -> bytes:
    return (name.encode() * (size // len(name) + 1))[:size]


def sib(name: str, size: int | None = None, lfs: bool = True):
    data = blob(name, size or 100)
    s = {"rfilename": name, "size": len(data)}
    if lfs:
        s["lfs"] = {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
    return s


REPOS = {
    GGUF_REPO: {"id": GGUF_REPO, "sha": "abc", "gated": False, "config": {}, "siblings": [
        {"rfilename": "README.md", "size": 10},
        sib("Mini-1B.F16.gguf", 4000), sib("Mini-1B.Q8_0.gguf", 2000), sib("Mini-1B.Q4_K_M.gguf", 1000),
        sib("mmproj-Mini-1B-F16.gguf", 300), sib("mtp-Mini-1B.gguf", 200),
    ]},
    "big/Big-GGUF": {"id": "big/Big-GGUF", "config": {}, "siblings": [
        sib("Q4_K_M/Big-Q4_K_M-00001-of-00002.gguf", 500), sib("Q4_K_M/Big-Q4_K_M-00002-of-00002.gguf", 400),
        sib("Big-Q8_0-00001-of-00003.gguf", 300), sib("Big-Q8_0-00002-of-00003.gguf", 300),
    ]},
    "openbmb/MiniCPM5-1B": {"id": "openbmb/MiniCPM5-1B", "config": {"model_type": "llama"}, "siblings": [
        {"rfilename": "config.json", "size": 700}, {"rfilename": "model-00000-of-00001.safetensors", "size": 9}]},
    "Qwen/Q-AWQ": {"id": "Qwen/Q-AWQ", "config": {"quantization_config": {"bits": 4, "quant_method": "awq"}},
                   "siblings": [{"rfilename": "model.safetensors", "size": 9}]},
    "Qwen/Q-GPTQ-Int4": {"id": "Qwen/Q-GPTQ-Int4", "config": {},
                         "siblings": [{"rfilename": "model.safetensors", "size": 9}]},
}


class FakeHub:
    """Enough of huggingface.co: the model-info API and ``resolve`` with Range."""

    def __init__(self):
        self.requests: list[httpx.Request] = []
        self.hold: asyncio.Event | None = None  # when set, file bodies stall after one chunk
        self.corrupt = False

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        parts = request.url.path.strip("/").split("/")
        if parts[:2] == ["api", "models"]:
            repo = REPOS.get("/".join(parts[2:4]))
            return httpx.Response(200, json=repo) if repo else httpx.Response(401, json={"error": "nope"})
        repo, rest = "/".join(parts[:2]), parts[2:]
        if rest[:1] != ["resolve"] or repo not in REPOS:
            return httpx.Response(404)
        name = "/".join(rest[2:])
        s = next((x for x in REPOS[repo]["siblings"] if x["rfilename"] == name), None)
        if s is None:
            return httpx.Response(404)
        data = blob(name, s["size"])
        if self.corrupt:
            data = b"x" + data[1:]
        start = 0
        if "range" in request.headers:
            start = int(request.headers["range"].split("=")[1].rstrip("-"))
            if start >= len(data):
                return httpx.Response(416)
        body = data[start:]
        if self.hold is not None:
            hold = self.hold

            async def stream():
                yield body[:10]
                await hold.wait()
                yield body[10:]
            return httpx.Response(206 if start else 200, content=stream())
        return httpx.Response(206 if start else 200, content=body)


@pytest.fixture
def hub():
    return FakeHub()


@pytest.fixture
def client(home, hub, monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "hf_test")
    with TestClient(create_app(home)) as c:
        c.app.state.lcpp.downloads.transport = httpx.MockTransport(hub)
        yield c


def wait_done(c, job_id, states=("done", "failed", "cancelled"), timeout=10):
    t0 = time.time()
    while time.time() - t0 < timeout:
        job = next(j for j in c.get("/api/downloads").json() if j["id"] == job_id)
        if job["state"] in states:
            return job
        time.sleep(0.02)
    raise AssertionError(f"download still {job['state']}")


# ---- parsing & classification ------------------------------------------
@pytest.mark.parametrize("text, want", [
    ("openbmb/MiniCPM5-1B", ("openbmb/MiniCPM5-1B", "main", None)),
    ("  openbmb/MiniCPM5-1B ", ("openbmb/MiniCPM5-1B", "main", None)),
    ("https://huggingface.co/openbmb/MiniCPM5-1B", ("openbmb/MiniCPM5-1B", "main", None)),
    ("huggingface.co/openbmb/MiniCPM5-1B/tree/dev", ("openbmb/MiniCPM5-1B", "dev", None)),
    (LINK, (GGUF_REPO, "main", "Mini-1B.Q4_K_M.gguf")),
    (f"https://hf.co/{GGUF_REPO}/blob/v2/sub/dir/x%20y.gguf", (GGUF_REPO, "v2", "sub/dir/x y.gguf")),
])
def test_parse_input(text, want):
    assert parse_input(text) == want


@pytest.mark.parametrize("text", ["", "MiniCPM5-1B", "https://example.com/a/b", "https://huggingface.co/only"])
def test_parse_input_rejects(text):
    from lcpp.instances import LcppError

    with pytest.raises(LcppError):
        parse_input(text)


def test_gguf_choices_group_splits_and_sidecars():
    g = gguf_choices(REPOS["big/Big-GGUF"]["siblings"])
    assert [(c["label"], c["quant"], len(c["files"]), c["complete"]) for c in g["choices"]] == [
        ("Big-Q8_0.gguf", "Q8_0", 2, False), ("Big-Q4_K_M.gguf", "Q4_K_M", 2, True)]
    assert g["choices"][1]["id"] == "Q4_K_M/Big-Q4_K_M-00001-of-00002.gguf"
    g = gguf_choices(REPOS[GGUF_REPO]["siblings"])
    assert [c["quant"] for c in g["choices"]] == ["Q4_K_M", "Q8_0", "F16"]  # smallest first
    assert [f["path"] for f in g["mmproj"]] == ["mmproj-Mini-1B-F16.gguf"]
    assert [f["path"] for f in g["drafts"]] == ["mtp-Mini-1B.gguf"]
    assert suggest_dir(GGUF_REPO) == "Mini-1B" and suggest_dir("a/Plain") == "Plain"


# ---- resolve -----------------------------------------------------------
def test_resolve_repo_offers_every_quant(client, hub):
    r = client.post("/api/downloads/resolve", json={"input": GGUF_REPO}).json()
    assert r["kind"] == "gguf" and r["message"] is None
    assert len(r["choices"]) == 3 and r["selected"] is None  # several quants: the user picks
    assert r["suggested_dir"] == "Mini-1B" and r["free_bytes"] > 0
    assert hub.requests[0].headers["authorization"] == "Bearer hf_test"


def test_resolve_link_preselects_its_file(client):
    r = client.post("/api/downloads/resolve", json={"input": LINK}).json()
    assert r["selected"] == "Mini-1B.Q4_K_M.gguf" and r["suggested_id"] == "mini-1b"
    bad = client.post("/api/downloads/resolve", json={"input": LINK.replace("Q4_K_M", "Q2_K")})
    assert bad.status_code == 404 and bad.json()["code"] == "hf_not_found"
    side = client.post("/api/downloads/resolve", json={"input": LINK.replace("Mini-1B.Q4_K_M", "mmproj-Mini-1B-F16")})
    assert side.status_code == 400 and "sidecar" in side.json()["detail"]


@pytest.mark.parametrize("repo, kind", [("openbmb/MiniCPM5-1B", "safetensors"), ("Qwen/Q-AWQ", "awq"),
                                        ("Qwen/Q-GPTQ-Int4", "gptq")])
def test_resolve_non_gguf_repo_says_what_it_is(client, repo, kind):
    r = client.post("/api/downloads/resolve", json={"input": repo}).json()
    assert r["kind"] == kind and r["choices"] == [] and "not GGUF" in r["message"]
    assert r["search_url"].startswith("https://huggingface.co/models?search=")


def test_resolve_unknown_repo(client):
    r = client.post("/api/downloads/resolve", json={"input": "nobody/nothing"})
    assert r.status_code == 404 and r.json()["code"] == "hf_not_found"


# ---- download ----------------------------------------------------------
def test_download_adds_model_with_sidecars(client, home):
    r = client.post("/api/downloads", json={
        "repo": GGUF_REPO, "choice": "Mini-1B.Q4_K_M.gguf", "mmproj": "mmproj-Mini-1B-F16.gguf",
        "draft": "mtp-Mini-1B.gguf", "model_id": "mini-1b", "nicknames": ["mini1b"]})
    assert r.status_code == 201, r.text
    job = wait_done(client, r.json()["id"])
    assert job["state"] == "done" and job["error"] is None and job["bytes_done"] == job["bytes_total"] == 1500
    d = home.root / "models/Mini-1B"
    assert (d / "Mini-1B.Q4_K_M.gguf").read_bytes() == blob("Mini-1B.Q4_K_M.gguf", 1000)
    assert not list(d.glob("*.part"))
    m = next(m for m in client.get("/api/models").json()["models"] if m["id"] == "mini-1b")
    assert m["ok"] and m["nicknames"] == ["mini1b"] and m["path"] == "models/Mini-1B/Mini-1B.Q4_K_M.gguf"
    assert m["capabilities"]["vision"] and m["capabilities"]["speculative"]
    saved = json.loads(home.models_file.read_text())["models"]["mini-1b"]
    assert saved["mmproj"] == "models/Mini-1B/mmproj-Mini-1B-F16.gguf" and saved["spec_type"] == "draft-mtp"
    assert client.delete(f"/api/downloads/{job['id']}").status_code == 204
    assert client.get("/api/downloads").json() == []


def test_download_resumes_a_part_file(client, home, hub):
    d = home.root / "models/Mini-1B"
    d.mkdir(parents=True)
    (d / "Mini-1B.Q8_0.gguf.part").write_bytes(blob("Mini-1B.Q8_0.gguf", 2000)[:1234])
    r = client.post("/api/downloads", json={"repo": GGUF_REPO, "choice": "Mini-1B.Q8_0.gguf", "add_to_catalog": False})
    job = wait_done(client, r.json()["id"])
    assert job["state"] == "done" and job["model_id"] is None
    assert [q.headers.get("range") for q in hub.requests if "resolve" in q.url.path] == ["bytes=1234-"]
    assert (d / "Mini-1B.Q8_0.gguf").read_bytes() == blob("Mini-1B.Q8_0.gguf", 2000)


def test_checksum_mismatch_fails_and_retry_recovers(client, home, hub):
    hub.corrupt = True
    r = client.post("/api/downloads", json={"repo": GGUF_REPO, "choice": "Mini-1B.Q4_K_M.gguf"})
    job = wait_done(client, r.json()["id"])
    assert job["state"] == "failed" and "checksum" in job["error"]
    assert not (home.root / "models/Mini-1B/Mini-1B.Q4_K_M.gguf.part").exists()
    hub.corrupt = False
    assert client.post(f"/api/downloads/{job['id']}/retry").json()["state"] == "queued"
    assert wait_done(client, job["id"])["state"] == "done"
    assert any(m["id"] == "mini-1b" for m in client.get("/api/models").json()["models"])


def test_cancel_removes_partial_files(client, home, hub, monkeypatch):
    monkeypatch.setattr("lcpp.downloads.CHUNK", 10)  # aiter_bytes buffers a whole chunk
    hub.hold = asyncio.Event()  # never set: the body stalls after 10 bytes
    r = client.post("/api/downloads", json={"repo": GGUF_REPO, "choice": "Mini-1B.Q8_0.gguf"})
    job_id = r.json()["id"]
    part = home.root / "models/Mini-1B/Mini-1B.Q8_0.gguf.part"
    t0 = time.time()
    while wait_done(client, job_id, states=("downloading",))["bytes_done"] != 10:
        assert time.time() - t0 < 5
        time.sleep(0.02)
    assert part.exists()
    job = client.post(f"/api/downloads/{job_id}/cancel").json()
    assert job["state"] == "cancelled" and not part.exists()
    assert not any(m["id"] == "mini-1b" for m in client.get("/api/models").json()["models"])


def test_download_rejects_bad_requests(client, home):
    def post(**kw):
        return client.post("/api/downloads", json={"repo": GGUF_REPO, "choice": "Mini-1B.Q4_K_M.gguf", **kw})
    assert "not a GGUF model" in post(choice="README.md").json()["detail"]
    assert "incomplete" in client.post("/api/downloads", json={
        "repo": "big/Big-GGUF", "choice": "Big-Q8_0-00001-of-00003.gguf"}).json()["detail"]
    assert "folder" in post(dir="../escape").json()["detail"]
    assert "already in the catalog" in post(model_id="minicpm-5-2B").json()["detail"]
    assert "already used by model" in post(nicknames=["MiniCPM5-2B"]).json()["detail"]
    assert "not a mmproj" in post(mmproj="Mini-1B.F16.gguf").json()["detail"]
    assert client.post("/api/downloads/nope/retry").json()["code"] == "download_not_found"
