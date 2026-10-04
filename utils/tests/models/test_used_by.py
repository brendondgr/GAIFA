"""3.4: "used by" from `[models] dirs`, ServiceDetail.models, and the in-use rule with a real fake mod."""

from __future__ import annotations

import re

import httpx
import pytest

from utils.tests.conftest import free_port
from utils.tests.models.conftest import Models
from utils.tests.services.conftest import until


def with_dirs(services, mod: str, dirs: list[str]) -> None:
    """Add `[models] dirs` to a copied fixture mod, and give it a free port."""
    toml = services / mod / "service.toml"
    text = re.sub(r"(?m)^port = \d+", f"port = {free_port()}", toml.read_text())
    toml.write_text(text + "\n[models]\ndirs = [" + ", ".join(f'"{d}"' for d in dirs) + "]\n")


@pytest.fixture
def tree(root):
    m = Models(root)
    m.put("comfyui/loras/style.safetensors", 64)
    m.put("comfyui/vae/vae.safetensors", 64)
    m.put("comfyui/loras-extra/other.safetensors", 64)  # "comfyui/loras" must not match "comfyui/loras-extra"
    m.put("tts/voice-model.safetensors", 64)
    m.write({
        "style": {"kind": "lora", "path": "comfyui/loras/style.safetensors", "files": [m.file("comfyui/loras/style.safetensors")]},
        "vae": {"kind": "vae", "path": "comfyui/vae/vae.safetensors", "files": [m.file("comfyui/vae/vae.safetensors")], "services": ["fake-ok"]},
        "other": {"kind": "lora", "path": "comfyui/loras-extra/other.safetensors", "files": [m.file("comfyui/loras-extra/other.safetensors")]},
        "speech": {"kind": "tts", "path": "tts/voice-model.safetensors", "files": [m.file("tts/voice-model.safetensors")]},
    })
    return m


async def test_used_by_dirs_and_explicit(services_dir, tree, make_app):
    services = services_dir("fake-ok", "fake-mem")
    with_dirs(services, "fake-ok", ["comfyui/loras/"])
    with_dirs(services, "fake-mem", ["tts", "comfyui"])
    app = make_app(port=7000, autostart=False)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://hub") as c:
            ms = {m["id"]: m["services"] for m in (await c.get("/api/models")).json()["models"]}
            # explicit services first, then mods by [models] dirs in sidebar order
            assert ms == {"style": ["fake-mem", "fake-ok"], "vae": ["fake-ok", "fake-mem"], "other": ["fake-mem"], "speech": ["fake-mem"]}
            assert (await c.get("/api/services/fake-ok")).json()["models"] == ["style", "vae"]
            assert (await c.get("/api/services/fake-mem")).json()["models"] == ["other", "speech", "style", "vae"]
            assert [m["id"] for m in (await c.get("/api/models", params={"service": "fake-ok"})).json()["models"]] == ["style", "vae"]


async def test_deleting_files_of_a_model_a_loaded_mod_uses_is_refused(services_dir, tree, make_app):
    """Phase 3 check: refused with model_in_use while the fake mod is loaded; allowed once it unloads."""
    services = services_dir("fake-mem")
    with_dirs(services, "fake-mem", ["tts"])
    app = make_app(port=7000, autostart=False)
    async with app.router.lifespan_context(app):
        mgr = app.state.hub.services
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://hub") as c:
            assert (await c.post("/api/services/fake-mem/start", params={"wait": 1})).json()["state"] == "ready"
            assert (await c.post("/api/services/fake-mem/load")).status_code == 202
            await until(lambda: mgr.get("fake-mem").load == "loaded", timeout=10)
            r = await c.delete("/api/models/speech", params={"files": 1})
            assert (r.status_code, r.json()["code"]) == (409, "model_in_use")
            assert r.json()["detail"] == "Fake Memory is running and uses speech. Stop or unload it first."
            assert (tree.dir / "tts/voice-model.safetensors").exists()
            await c.post("/api/services/fake-mem/unload")
            await until(lambda: mgr.get("fake-mem").load == "unloaded", timeout=10)
            assert (await c.delete("/api/models/speech", params={"files": 1})).status_code == 204
            assert not (tree.dir / "tts").exists()
            await c.post("/api/services/fake-mem/stop", params={"wait": 1})
