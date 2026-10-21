"""Shared fixtures: settings in a temporary folder, the fake backend, and a fake hub that serves outputs
(images labelled in a PNG text chunk, so the fake backend can match them to text) and records calls."""

from __future__ import annotations

import io
import json
import math
import struct
import subprocess
import wave
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image, PngImagePlugin

from embed.encoder import Encoder, FakeBackend
from embed.hubclient import Hub
from embed.server import create_app
from embed.settings import Settings


def png(label: str, color: str = "red", size: tuple[int, int] = (64, 48)) -> bytes:
    meta = PngImagePlugin.PngInfo()
    meta.add_text("label", label)
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG", pnginfo=meta)
    return buf.getvalue()


def wav(seconds: float, rate: int = 44100, channels: int = 2) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * 440 * i / rate))) * channels
                          for i in range(int(seconds * rate)))
        w.writeframes(frames)
    return buf.getvalue()


def mp4(tmp: Path, seconds: int, name: str = "v.mp4") -> bytes:
    out = tmp / name
    subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    f"testsrc=duration={seconds}:size=160x120:rate=12", "-f", "lavfi", "-i",
                    f"sine=frequency=330:duration={seconds}", "-shortest", "-pix_fmt", "yuv420p", str(out)], check=True)
    return out.read_bytes()


class FakeHub:
    """Outputs by id (`add`; text outputs answer the text route with windows and pages), memory acquire
    (`room = False` answers 409 needs_room), model registration, and chat threads' events."""

    def __init__(self):
        self.outputs: dict[str, tuple[dict, bytes]] = {}
        self.texts: dict[str, tuple[str, list[int]]] = {}
        self.previews: dict[str, bytes] = {}
        self.threads: dict[str, list[dict]] = {}
        self.acquires: list[dict] = []
        self.models: list[dict] = []
        self.room = True
        self.window = 48_000
        self.clock = 1_000_000.0

    def add(self, oid: str, kind: str, data: bytes = b"", title: str | None = None, meta: dict | None = None,
            text: str | None = None, pages: list[str] | None = None, preview: bytes | None = None, hidden: bool = False) -> str:
        if pages is not None:
            starts, acc = [], ""
            for p in pages:
                starts.append(len(acc))
                acc += p
            self.texts[oid] = (acc, starts)
            data = acc.encode()
        elif text is not None:
            self.texts[oid] = (text, [])
            data = text.encode()
        self.clock += 1
        rec = {"id": oid, "kind": kind, "size_bytes": len(data), "service": "test", "title": title or oid,
               "files": [{"path": f"outputs/test/{oid}", "kind": kind, "size_bytes": len(data)}],
               "preview": f"/api/outputs/{oid}/preview?v=1" if preview else None, "created_ts": self.clock,
               "meta": meta or {}, **({"hidden": True} if hidden else {})}
        if preview:
            self.previews[oid] = preview
        self.outputs[oid] = (rec, data)
        return f"output:{oid}"

    def remove(self, oid: str) -> None:
        self.outputs.pop(oid, None)
        self.texts.pop(oid, None)

    def _text(self, oid: str, params) -> httpx.Response:
        if oid not in self.texts:
            return httpx.Response(409, json={"detail": "no text", "code": "not_text"})
        text, starts = self.texts[oid]
        limit = min(int(params.get("limit", 12_000)), self.window)
        if params.get("pages"):
            p = int(params["pages"])
            start = starts[p - 1]
        else:
            start = min(int(params.get("offset", 0)), len(text))
        end = min(len(text), start + limit)
        return httpx.Response(200, json={"text": text[start:end], "offset": start, "next_offset": end if end < len(text) else None,
                                         "total_chars": len(text), "pages": len(starts), "lines": text.count("\n") + 1})

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/memory/acquire":
            body = json.loads(request.content)
            self.acquires.append(body)
            if not self.room:
                return httpx.Response(409, json={"detail": "Not enough memory", "code": "needs_room",
                                                 "data": {"plan": {"unload": []}}})
            return httpx.Response(200, json={"granted": True, "freed": []})
        if path == "/api/models":
            self.models.append(json.loads(request.content))
            return httpx.Response(201, json={"id": "embeddinggemma-2"})
        if path == "/api/outputs":
            items = sorted((r for r, _ in self.outputs.values()
                            if not r.get("hidden") or request.url.params.get("include_hidden") == "true"), key=lambda r: -r["created_ts"])
            start = int(request.url.params.get("cursor") or 0)
            limit = int(request.url.params.get("limit") or 60)
            nxt = start + limit if start + limit < len(items) else None
            return httpx.Response(200, json={"items": items[start:start + limit], "next_cursor": str(nxt) if nxt else None})
        if path.startswith("/api/s/agent/v1/threads/"):
            tid = path.split("/")[6]
            if tid not in self.threads:
                return httpx.Response(404, json={"detail": "no thread", "code": "not_found"})
            return httpx.Response(200, json=self.threads[tid])
        if path.startswith("/api/outputs/"):
            oid, _, rest = path.removeprefix("/api/outputs/").partition("/")
            if oid not in self.outputs:
                return httpx.Response(404, json={"detail": "no such output", "code": "not_found"})
            rec, data = self.outputs[oid]
            if rest == "file":
                return httpx.Response(200, content=data)
            if rest == "preview":
                return httpx.Response(200, content=self.previews[oid]) if oid in self.previews else httpx.Response(404)
            if rest == "text":
                return self._text(oid, request.url.params)
            return httpx.Response(200, json=rec)
        return httpx.Response(404, json={"detail": "not here", "code": "not_found"})


class FakeGpu:
    """AIHub's GPU queue for one test (plan 31.3). `blocked` holds back leases of these classes (another mod's work
    runs or waits: acquire answers 202 after a short wait); `cancel_after` grants that many leases, then answers
    the next one as cancelled from the queue. `log` lists (event, class), `held` the leases not yet released."""

    def __init__(self, blocked: set[str] | None = None, cancel_after: int | None = None):
        self.blocked = blocked or set()
        self.cancel_after = cancel_after
        self.log: list[tuple[str, str]] = []
        self.held: dict[str, str] = {}
        self.granted = 0

    async def handler(self, request: httpx.Request) -> httpx.Response:
        import asyncio

        body = json.loads(request.content or b"{}")
        path = request.url.path
        if path == "/api/gpu/acquire":
            cls, lid = body.get("class"), body["lease"]
            if self.cancel_after is not None and self.granted >= self.cancel_after:
                self.log.append(("cancelled", cls))
                return httpx.Response(200, json={"lease": lid, "state": "cancelled"})
            if cls in self.blocked:
                if ("wait", cls) not in self.log[-1:]:
                    self.log.append(("wait", cls))
                await asyncio.sleep(0.01)
                return httpx.Response(202, json={"lease": lid, "state": "waiting", "eta_s": 120, "ahead": [
                    {"id": "gl_other", "service": "comfy", "label": "image", "state": "held", "eta_s": 120}]})
            self.granted += 1
            self.held[lid] = cls
            self.log.append(("granted", cls))
            return httpx.Response(200, json={"lease": lid, "state": "granted"})
        lid = path.split("/")[3]
        if path.endswith("/release"):
            cls = self.held.pop(lid, None)
            self.log.append(("released", cls or "?"))
        return httpx.Response(200, json={"lease": lid, "state": "granted"})

    def slot(self, service: str = "embed"):
        from embed.gpu_slot import GpuSlot

        return GpuSlot(hub_url="http://hub", service=service, transport=httpx.MockTransport(self.handler), poll_s=0.05)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    model = tmp_path / "models" / "embed" / "embeddinggemma-2"
    model.mkdir(parents=True)
    (model / "model.safetensors").write_bytes(b"fake")
    return Settings(port=0, model_dir=model, state_dir=tmp_path / "state", hub_url="http://hub", idle_unload_s=0,
                    batch_text=32, batch_media=4, databases=tmp_path / "db", index=False)


@pytest.fixture
def hub() -> FakeHub:
    return FakeHub()


@pytest.fixture
def backend() -> FakeBackend:
    return FakeBackend()


@pytest.fixture
def encoder(backend: FakeBackend, settings: Settings) -> Encoder:
    return Encoder(backend, settings.state_dir)


@pytest.fixture
def client(settings: Settings, encoder: Encoder, hub: FakeHub):
    app = create_app(settings, encoder=encoder, hub=Hub(settings.hub_url, transport=httpx.MockTransport(hub.handler)))
    with TestClient(app) as c:
        yield c
