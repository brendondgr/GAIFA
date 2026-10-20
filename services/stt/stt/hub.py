"""The two things this mod asks of AIHub, over HTTP: an output's file, and registering weights."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import httpx

from . import catalog

logger = logging.getLogger(__name__)


class HubError(ValueError):
    pass


def output_id(ref: str) -> str:
    """``output:<id>`` or a bare id → the id."""
    ref = ref.strip()
    return ref.split(":", 1)[1] if ref.startswith("output:") else ref


class Hub:
    def __init__(self, url: str) -> None:
        self.url = url.rstrip("/")

    async def fetch_output(self, ref: str, folder: Path, name: str) -> tuple[Path, dict[str, Any]]:
        """Download an output's main file into ``folder``; returns (path, the output's record)."""
        oid = output_id(ref)
        async with httpx.AsyncClient(timeout=httpx.Timeout(30, read=600)) as c:
            try:
                meta = await c.get(f"{self.url}/api/outputs/{oid}")
            except httpx.HTTPError as exc:
                raise HubError(f"AIHub didn't answer at {self.url} ({exc}); upload the file instead") from exc
            if meta.status_code == 404:
                raise HubError(f"no output {oid!r}")
            meta.raise_for_status()
            record = meta.json()
            if record.get("kind") not in ("audio", "video"):
                raise HubError(f"output {oid!r} is {record.get('kind')}, not audio or video")
            suffix = Path(str(record.get("path") or "")).suffix or ".bin"
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / f"{name}{suffix}"
            async with c.stream("GET", f"{self.url}/api/outputs/{oid}/file") as r:
                if r.status_code >= 400:
                    raise HubError(f"couldn't fetch output {oid!r} (HTTP {r.status_code})")
                with path.open("wb") as f:
                    async for chunk in r.aiter_bytes(1 << 20):
                        f.write(chunk)
        return path, record

    async def register_model(self, name: str, fetched: dict[str, Any]) -> None:
        """Add ``stt/<name>`` to the models registry (409 = already there, which is fine)."""
        info = catalog.BY_NAME[name]
        body = {"path": f"stt/{name}", "name": f"Whisper {name} (faster-whisper)", "kind": "stt",
                "source": {"type": "huggingface", "repo": info.repo,
                           **({"revision": fetched["revision"]} if fetched.get("revision") else {})}}
        try:
            async with httpx.AsyncClient(timeout=60) as c:
                r = await c.post(f"{self.url}/api/models", json=body)
            if r.status_code not in (200, 201, 409):
                logger.warning("Registering %s answered HTTP %s: %s", name, r.status_code, r.text[:200])
        except httpx.HTTPError as exc:
            logger.warning("Couldn't register %s with AIHub: %s", name, exc)

    async def register_present(self, weights: Path) -> None:
        """Register every model whose weights are here (copied in by hand, or before AIHub knew)."""
        for info in catalog.CATALOG:
            if catalog.is_downloaded(weights, info.name):
                await self.register_model(info.name, catalog.recorded_source(weights, info.name))
