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
    """Outputs by id (`add`), memory acquire (`room = False` answers 409 needs_room), model registration."""

    def __init__(self):
        self.outputs: dict[str, tuple[dict, bytes]] = {}
        self.acquires: list[dict] = []
        self.models: list[dict] = []
        self.room = True

    def add(self, oid: str, kind: str, data: bytes) -> str:
        self.outputs[oid] = ({"id": oid, "kind": kind, "size_bytes": len(data), "service": "test"}, data)
        return f"output:{oid}"

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
        if path.startswith("/api/outputs/"):
            oid, _, rest = path.removeprefix("/api/outputs/").partition("/")
            if oid not in self.outputs:
                return httpx.Response(404, json={"detail": "no such output", "code": "not_found"})
            rec, data = self.outputs[oid]
            return httpx.Response(200, content=data) if rest == "file" else httpx.Response(200, json=rec)
        return httpx.Response(404, json={"detail": "not here", "code": "not_found"})


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    model = tmp_path / "models" / "embed" / "embeddinggemma-2"
    model.mkdir(parents=True)
    (model / "model.safetensors").write_bytes(b"fake")
    return Settings(port=0, model_dir=model, state_dir=tmp_path / "state", hub_url="http://hub", idle_unload_s=0,
                    batch_text=32, batch_media=4)


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
