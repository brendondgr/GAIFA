"""11.8: imports from files and history become draft packs; saving, deleting and downloads."""

import asyncio
import io
import json
import shutil
import subprocess
import time
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from PIL.PngImagePlugin import PngInfo

from comfy import importer
from comfy.downloads import Downloads
from comfy.nodes import NodeCatalog
from comfy.packs import Packs
from comfy.server import create_app
from fakecomfy import FakeComfy, FakeHub

FIX = Path(__file__).parent / "fixtures"
INFO = json.loads((FIX / "object_info.json").read_text())
EDITOR = json.loads((FIX / "workflows" / "zit-workflow.json").read_text())
API = json.loads((FIX / "workflows" / "zit-workflow.api.json").read_text())


def png(meta: dict) -> bytes:
    info = PngInfo()
    for k, v in meta.items():
        info.add_text(k, json.dumps(v))
    b = io.BytesIO()
    Image.new("RGB", (8, 8)).save(b, "PNG", pnginfo=info)
    return b.getvalue()


@pytest.fixture
def env(tmp_path, settings):
    with FakeComfy(INFO, up=True) as fake:
        s = settings.__class__(**{**settings.__dict__, "comfy_url": fake.url})
        with TestClient(create_app(s)) as c:
            c.app.state.catalog.save(INFO)
            yield c, fake, s


def test_read_formats():
    f = importer.read_file("a.png", png({"workflow": EDITOR, "prompt": API}))
    assert f.editor["nodes"] and f.api == API
    assert importer.read_file("b.png", png({"prompt": API})).editor is None
    b = io.BytesIO()
    exif = Image.Exif()
    exif[0x010E] = "workflow:" + json.dumps(EDITOR)
    exif[0x010F] = "prompt:" + json.dumps(API)
    Image.new("RGB", (8, 8)).save(b, "WEBP", exif=exif)
    w = importer.read_file("c.webp", b.getvalue())
    assert w.editor and w.api == API
    with pytest.raises(importer.ImportError_, match="no ComfyUI workflow"):
        importer.read_file("d.png", png({}))
    with pytest.raises(importer.ImportError_):
        importer.read_file("e.txt", b"hello")


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")
def test_read_video(tmp_path):
    out = tmp_path / "v.mp4"
    subprocess.run(["ffmpeg", "-v", "quiet", "-f", "lavfi", "-i", "color=c=black:s=16x16:d=0.2", "-metadata",
                    f"prompt={json.dumps(API)}", "-movflags", "use_metadata_tags", str(out)], check=True)
    assert importer.read_file("v.mp4", out.read_bytes()).api == API


def test_zip_with_assets():
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("Cool Pack v2/Cool Pack.json", json.dumps(EDITOR))
        z.writestr("Cool Pack v2/luts/Blue.cube", "LUT")
        z.writestr("Cool Pack v2/workflow.png", png({"workflow": EDITOR}))
    f = importer.read_file("cool.zip", b.getvalue())
    assert f.editor and set(f.assets) == {"luts/Blue.cube", "workflow.png"}


def test_import_route_save_and_delete(env):
    c, fake, s = env
    r = c.post("/v1/import", files={"file": ("My Z-Image.png", png({"workflow": EDITOR, "prompt": API}), "image/png")})
    assert r.status_code == 201, r.json()
    body = r.json()
    assert body["id"] == "my-z-image" and body["workflow"]["state"] == "draft"
    assert (s.workflows / "my-z-image" / "workflow.json").exists()
    assert not (s.workflows / "my-z-image" / "workflow.api.json").exists()   # the editor converts: API not pinned
    sug = body["suggestion"]
    assert sug["manifest"]["task"] == "text-to-image" and "[inputs.prompt]" in sug["toml"]
    # saving the suggestion (as edited TOML) turns the draft into a pack
    toml = sug["toml"].replace('name = "My z image"', 'name = "My Z-Image"')
    saved = c.put("/v1/workflows/my-z-image", json={"toml": toml}).json()
    assert saved["state"] == "ready" and saved["name"] == "My Z-Image"
    assert "# CLIPTextEncode" in (s.workflows / "my-z-image" / "workflow.toml").read_text()      # comments kept
    bad = c.put("/v1/workflows/my-z-image", json={"toml": 'name = "x"\nbogus = 1\n'})
    assert bad.status_code == 422 and "bogus" in bad.json()["detail"]
    # the JSON form, with presets and [set]
    m = dict(sug["manifest"], presets={"square": {"width": 1024, "height": 1024}}, set={"70.steps": 6})
    assert c.put("/v1/workflows/my-z-image", json={"manifest": m}).json()["presets"] == {"square": {"width": 1024, "height": 1024}}
    # API-only files keep the API graph
    r2 = c.post("/v1/import", files={"file": ("graph.json", json.dumps(API).encode(), "application/json")}, data={"id": "exact"}).json()
    assert (s.workflows / "exact" / "workflow.api.json").exists() and r2["id"] == "exact"
    assert c.delete("/v1/workflows/exact").json() == {"removed": "exact"}
    assert not (s.workflows / "exact").exists() and list((s.workflows / ".trash").iterdir())
    assert c.post("/v1/import", files={"file": ("x.txt", b"nope", "text/plain")}).status_code == 422


def test_import_from_history(env):
    c, fake, s = env
    fake.history["abc123"] = {"prompt": [5, "abc123", API, {"extra_pnginfo": {"workflow": EDITOR}}, []],
                              "outputs": {"77": {"images": [{"filename": "x.png", "subfolder": "", "type": "output"}]}},
                              "status": {"status_str": "success"}}
    items = c.get("/v1/import/history").json()["items"]
    assert items[0]["prompt_id"] == "abc123" and items[0]["has_editor"] and items[0]["files"] == ["x.png"]
    r = c.post("/v1/import/history/abc123", json={"id": "from-history"}).json()
    assert r["id"] == "from-history" and (s.workflows / "from-history" / "workflow.json").exists()
    assert c.post("/v1/import/history/nope", json={}).status_code == 404
    # 51.3: GAIFA's own prompts from before the rename carry "aihub" instead of "gaifa"
    for key, pid in (("gaifa", "new1"), ("aihub", "old1")):
        fake.history[pid] = {"prompt": [6, pid, API, {"extra_pnginfo": {key: {"workflow": "zimage", "run": "r-1"}}}, []],
                             "outputs": {}, "status": {"status_str": "success"}}
    made = {i["prompt_id"]: i["from_gaifa"] for i in c.get("/v1/import/history").json()["items"]}
    assert made["new1"] == made["old1"] == "zimage" and made["abc123"] is None


def test_reimport_of_a_result_png_gives_the_same_graph(tmp_path):
    """A PNG ComfyUI saved (with only the API graph) imports to exactly that graph."""
    f = importer.read_file("143619-a-fox_00001_.png", png({"prompt": API, "gaifa": {"workflow": "zimage"}}))
    from comfy.packs import Packs
    packs = Packs(tmp_path / "wf")
    pid = importer.create(packs, NodeCatalog(INFO), f, None, "143619-a-fox_00001_.png")
    assert json.loads((tmp_path / "wf" / pid / "workflow.api.json").read_text()) == API


def test_downloads_register_in_gaifa(tmp_path):
    async def go():
        with FakeHub() as hub:
            d = Downloads(tmp_path / "models", hub.url, allow_http=True)
            dl = d.start(f"{hub.url}/files/wan_vae.safetensors", "vae")
            for _ in range(100):
                if dl.state in ("done", "failed"):
                    break
                await asyncio.sleep(0.05)
            assert dl.state == "done", dl.error
            assert (tmp_path / "models" / "vae" / "wan_vae.safetensors").stat().st_size == 1000
            assert hub.registered[0]["path"] == "comfyui/vae/wan_vae.safetensors" and hub.registered[0]["kind"] == "vae"
            with pytest.raises(FileExistsError):
                d.start(f"{hub.url}/files/wan_vae.safetensors", "vae")
            with pytest.raises(ValueError):
                d.start(f"{hub.url}/files/x.safetensors", "../etc")
            with pytest.raises(ValueError):
                Downloads(tmp_path).start("http://example.com/x.safetensors", "vae")
    asyncio.run(go())


def test_zip_with_several_workflows_imports_each(env):
    """A Civitai pack with four variants imported only one, silently (held-out, 11.12)."""
    c, fake, s = env
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("ZImgBasic.json", json.dumps(EDITOR))
        z.writestr("ZImgFull.json", json.dumps(EDITOR))
        z.writestr("readme.txt", "hi")
    r = c.post("/v1/import", files={"file": ("pack.zip", b.getvalue(), "application/zip")}, data={"id": "zpack"}).json()
    assert r["id"] == "zpack-1" and r["also"] == ["zpack-2"]
    assert (s.workflows / "zpack-2" / "assets" / "readme.txt").exists()


def test_cli_imports_media_and_zips_from_relative_paths(tmp_path, settings, monkeypatch, capsys):
    """The CLI only read JSON, and its wrapper changed folder so relative paths failed (11.12)."""
    from comfy import cli
    for k, v in {"COMFY_WORKFLOWS": settings.workflows, "COMFY_VIEW": settings.comfy_view, "COMFY_DATA": settings.data}.items():
        monkeypatch.setenv(k, str(v))
    monkeypatch.setenv("GAIFA_URL", "http://127.0.0.1:1")
    settings.data.mkdir(parents=True)
    (settings.data / "object_info.json").write_text((FIX / "object_info.json").read_text())
    (tmp_path / "shot.png").write_bytes(png({"workflow": EDITOR, "prompt": API}))
    monkeypatch.chdir(tmp_path)
    assert cli.main(["new", "from-png", "--from", "shot.png"]) == 0
    assert (settings.workflows / "from-png" / "workflow.json").exists()
    assert "made workflows/from-png/ (editor file)" in capsys.readouterr().out


def test_zip_entries_cant_write_outside_the_pack(tmp_path):
    """An entry named /home/…/.bashrc beside the workflow became the asset "//home/…", and
    d/"assets"/"//home/…" is that absolute path: the import wrote it."""
    target = tmp_path / "escaped.txt"
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("wf.json", json.dumps(EDITOR))
        z.writestr(str(target), b"WRITTEN-OUTSIDE")
        z.writestr("C:/luts/Blue.cube", "LUT")
        z.writestr("../../up.txt", "UP")
    f = importer.read_file("pack.zip", b.getvalue())
    assert all(not k.startswith("/") and ".." not in k.split("/") for k in f.assets), f.assets
    packs = Packs(tmp_path / "wf")
    pid = importer.create(packs, None, f, "evil", "pack.zip")
    assert not target.exists() and not (tmp_path / "up.txt").exists()
    assets = tmp_path / "wf" / pid / "assets"
    written = {str(p.relative_to(assets)) for p in assets.rglob("*") if p.is_file()}
    assert written == {str(target).lstrip("/"), "luts/Blue.cube", "up.txt"}
    f.assets["//etc/x"] = b"x"                                   # whatever a reader hands it, create stays inside
    f.assets["a\\..\\..\\y"] = b"y"
    importer.create(packs, None, f, "evil2", "pack.zip")
    assert not (tmp_path / "wf" / "evil2" / "assets" / "etc").exists()


def test_zip_symlinks_and_backslashes_are_refused():
    for entry, attr in (("assets/link", (0o120777 << 16)), ("luts\\Blue.cube", 0o100644 << 16)):
        b = io.BytesIO()
        with zipfile.ZipFile(b, "w") as z:
            z.writestr("wf.json", json.dumps(EDITOR))
            info = zipfile.ZipInfo(entry)
            info.external_attr = attr
            z.writestr(info, "/home/bdgr/.ssh/id_ed25519")
        with pytest.raises(importer.ImportError_):
            importer.read_file("pack.zip", b.getvalue())


def test_hf_token_goes_only_to_huggingface(tmp_path, monkeypatch):
    """netloc.endswith("huggingface.co") sent HF_TOKEN to nothuggingface.co; redirects to http were followed."""
    import comfy.downloads as dls
    import httpx
    seen: list[tuple[str, str | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((str(request.url), request.headers.get("authorization")))
        if request.url.path.endswith("/to-http"):
            return httpx.Response(302, headers={"location": "http://huggingface.co/plain.safetensors"})
        return httpx.Response(200, content=b"x" * 1000)

    real = httpx.AsyncClient
    monkeypatch.setattr(dls.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setenv("HF_TOKEN", "hf_secret")

    async def go(url, name, limit=None):
        if limit:
            monkeypatch.setattr(dls, "MAX_BYTES", limit)
        d = Downloads(tmp_path / "models")
        dl = d.start(url, "vae", name)
        for _ in range(100):
            if dl.state in ("done", "failed"):
                break
            await asyncio.sleep(0.02)
        return dl

    assert asyncio.run(go("https://nothuggingface.co/x.safetensors", "a.safetensors")).state == "done"
    assert seen[-1][1] is None
    asyncio.run(go("https://huggingface.co.evil.example/x.safetensors", "b.safetensors"))
    assert seen[-1][1] is None
    asyncio.run(go("https://cdn-lfs.huggingface.co/x.safetensors", "c.safetensors"))
    assert seen[-1][1] == "Bearer hf_secret"
    dl = asyncio.run(go("https://huggingface.co/to-http", "d.safetensors"))
    assert dl.state == "failed" and "https" in dl.error and not (tmp_path / "models" / "vae" / "d.safetensors").exists()
    dl = asyncio.run(go("https://huggingface.co/big.safetensors", "e.safetensors", limit=500))
    assert dl.state == "failed" and not (tmp_path / "models" / "vae" / "e.safetensors").exists()
