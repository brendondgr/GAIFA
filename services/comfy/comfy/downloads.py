"""Downloading a missing model file into data/models/comfyui/<folder>/ (plan 11.8), then registering
it in AIHub's models registry. The page asks the user to confirm each one first."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import urlparse

import httpx

log = logging.getLogger("comfy")
FOLDERS = {"checkpoints", "clip", "clip_vision", "controlnet", "diffusers", "diffusion_models", "embeddings", "gligen",
           "hypernetworks", "latent_upscale_models", "loras", "model_patches", "photomaker", "style_models",
           "text_encoders", "unet", "upscale_models", "vae", "vae_approx", "audio_encoders", "ultralytics"}
KIND = {"diffusion_models": "image", "unet": "image", "checkpoints": "image", "text_encoders": "text-encoder",
        "clip": "text-encoder", "vae": "vae", "loras": "lora", "clip_vision": "vision", "upscale_models": "upscale",
        "latent_upscale_models": "upscale"}
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,200}$")


@dataclass
class Download:
    id: str
    url: str
    folder: str
    name: str
    state: str = "queued"          # queued | running | done | failed
    bytes: int = 0
    total: int | None = None
    error: str | None = None
    created: float = field(default_factory=time.time)
    registered: str | None = None

    def json(self) -> dict:
        return asdict(self)


class Downloads:
    def __init__(self, models: Path, hub_url: str = "", allow_http: bool = False):
        self.models, self.hub_url, self.allow_http = models, hub_url, allow_http   # http only for tests
        self.items: dict[str, Download] = {}
        self._tasks: set[asyncio.Task] = set()

    def start(self, url: str, folder: str, name: str | None = None) -> Download:
        u = urlparse(url)
        if u.scheme not in (("https", "http") if self.allow_http else ("https",)) or not u.netloc:
            raise ValueError("only https URLs can be downloaded")
        if folder not in FOLDERS:
            raise ValueError(f"folder must be one of: {', '.join(sorted(FOLDERS))}")
        name = name or Path(u.path).name
        if not NAME_RE.match(name):
            raise ValueError(f"{name!r} isn't a usable file name")
        dest = self.models / folder / name
        if dest.exists():
            raise FileExistsError(f"{folder}/{name} is already there")
        if any(d.folder == folder and d.name == name and d.state in ("queued", "running") for d in self.items.values()):
            raise FileExistsError(f"{folder}/{name} is already downloading")
        dl = Download("d-" + uuid.uuid4().hex[:8], url, folder, name)
        self.items[dl.id] = dl
        t = asyncio.create_task(self._run(dl))
        self._tasks.add(t)
        t.add_done_callback(self._tasks.discard)
        return dl

    async def _run(self, dl: Download) -> None:
        dest = self.models / dl.folder / dl.name
        part = dest.with_name(dest.name + ".part")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dl.state = "running"
        headers = {}
        token = os.environ.get("HF_TOKEN")
        if token and urlparse(dl.url).netloc.endswith("huggingface.co"):
            headers["Authorization"] = f"Bearer {token}"
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=httpx.Timeout(30, read=300)) as c:
                async with c.stream("GET", dl.url, headers=headers) as r:
                    if r.status_code >= 400:
                        raise RuntimeError(f"the server answered {r.status_code}")
                    dl.total = int(r.headers.get("content-length") or 0) or None
                    with part.open("wb") as f:
                        async for chunk in r.aiter_bytes(1 << 20):
                            f.write(chunk)
                            dl.bytes += len(chunk)
            os.replace(part, dest)
            dl.state = "done"
            log.info("downloaded %s/%s (%d bytes)", dl.folder, dl.name, dl.bytes)
            dl.registered = await self._register(dl)
        except Exception as e:  # noqa: BLE001
            dl.state, dl.error = "failed", str(e)
            part.unlink(missing_ok=True)
            log.warning("download of %s failed: %s", dl.url, e)

    async def _register(self, dl: Download) -> str | None:
        """POST /api/models; returns the registry id, or None."""
        if not self.hub_url:
            return None
        rel = f"comfyui/{dl.folder}/{dl.name}"
        u = urlparse(dl.url)
        repo = "/".join(u.path.strip("/").split("/")[:2]) if u.netloc.endswith("huggingface.co") else None
        kind = KIND.get(dl.folder, "other")
        if kind == "image" and re.search(r"wan|video|hunyuan|ltx|scail", dl.name, re.I):
            kind = "video"
        body = {"path": rel, "kind": kind, "name": Path(dl.name).stem, "services": ["comfy"],
                "source": {"type": "huggingface", "repo": repo, "revision": "main"} if repo else {"type": "url", "url": dl.url},
                "files": [{"path": rel, "role": "weights"}]}
        try:
            async with httpx.AsyncClient(timeout=30) as c:
                r = await c.post(f"{self.hub_url}/api/models", json=body)
            if r.status_code < 400:
                return r.json().get("id")
            log.warning("AIHub didn't register %s: %s", rel, r.text[:200])
        except httpx.HTTPError as e:
            log.warning("AIHub didn't register %s: %s", rel, e)
        return None
