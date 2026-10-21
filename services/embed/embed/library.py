"""The library (plan 28.2): every output in AIHub, indexed for search by meaning.

It follows the hub over HTTP: `GET /api/outputs` on every (re)connect to `/api/events` (new, changed and deleted
outputs since the last look), then `output` and `output_deleted` events. Each output becomes chunks in
`embed.db`: a `meta` chunk from its title and prompt for every output; text and documents through the hub's text
route (24.3), in ~800-token chunks that keep page and line; an image (a 3D model's preview); a video whole; audio
whole plus 30 s windows when it's long.

Indexing waits for the GPU (decided 2026-10-20): it starts once the GPU has stayed under `idle_busy_pct` for
`idle_seconds`, looks again between batches and stops as soon as something else uses it, and unloads the model
when the queue is empty (unless a search used it in the last minute). Loading for indexing never evicts another
mod: a 409 from the hub's memory acquire just waits.
"""

from __future__ import annotations

import asyncio
import contextvars
import hashlib
import json
import logging
import os
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

from . import chunks as chunking
from . import media
from .encoder import Encoder, prompt
from .gpu import DeviceMedian, GpuIdle, HubMeter
from .hubclient import Hub, HubError
from .settings import Settings
from .store import Chunk, Store

log = logging.getLogger("embed")
MAX_BYTES = {"image": 64_000_000, "audio": 512_000_000, "video": 2_000_000_000, "model3d": 64_000_000}
LONG_AUDIO_S = 60
API_KEEP_S = 60            # a search in the last minute keeps the model loaded after indexing
GATED = contextvars.ContextVar("gated", default=True)    # False while a search indexes its own outputs (28.3)


class Stop(Exception):
    """The GPU went busy between batches: leave the output pending and wait again."""


def signature(rec: dict[str, Any]) -> str:
    """What changes when an output's content does: its files and sizes, its preview (whose URL carries the
    hub's own signature) and its title and prompt."""
    meta = rec.get("meta") or {}
    key = [rec.get("kind"), rec.get("title"), rec.get("size_bytes"), [(f.get("path"), f.get("size_bytes")) for f in rec.get("files") or []],
           rec.get("preview"), meta.get("prompt")]
    return hashlib.sha1(json.dumps(key, sort_keys=True, default=str).encode()).hexdigest()[:16]


FILE_NAME = re.compile(r"^[\w\-. ()]+\.[A-Za-z0-9]{1,5}$")


def meta_text(rec: dict[str, Any]) -> str:
    """The title and prompt as text. A title that is only a file name (`IMG_2041.png`, `sample.jpg`) with no
    prompt says nothing about the output: no meta chunk, or it would match every query a little."""
    meta = rec.get("meta") or {}
    title = str(rec.get("title") or "").strip()
    parts = [] if FILE_NAME.match(title) else [title]
    for k in ("prompt", "text", "description"):
        v = meta.get(k)
        if isinstance(v, str) and v.strip() and v.strip() not in parts:
            parts.append(v.strip()[:2000])
    return ". ".join(p for p in parts if p)


class Library:
    def __init__(self, store: Store, enc: Encoder, hub: Hub, settings: Settings, gpu: GpuIdle | None = None,
                 sleep: Callable[[float], Any] = asyncio.sleep):
        self.store, self.enc, self.hub, self.s = store, enc, hub, settings
        if gpu is None:
            device = DeviceMedian(settings.idle_window_s)
            read = device if settings.idle_measure == "device" else HubMeter(
                settings.hub_url, os.environ.get("AIHUB_SERVICE_ID", "embed"), device, settings.idle_device_pct)
            pct = settings.idle_device_pct if settings.idle_measure == "device" else settings.idle_busy_pct
            gpu = GpuIdle(pct, settings.idle_seconds, ours=lambda: enc.busy or enc.loading, read=read)
        self.gpu = gpu
        self.sleep = sleep
        self.tmp = settings.state_dir / "tmp"
        self.wake = asyncio.Event()
        self.state = "starting"            # starting | idle | waiting_for_gpu | indexing | no_room | no_hub
        self.current: dict[str, Any] | None = None
        self.last_api = 0.0                # the server sets this on every /v1/embed and search
        self.indexed = 0
        self.connected = False
        self._in_chats = False

    # following the hub ----------------------------------------------------------------------

    async def reconcile(self) -> dict[str, int]:
        """Bring the index in line with the hub's outputs: queue new and changed ones, drop deleted ones."""
        known = self.store.sigs()
        seen: set[str] = set()
        queued = 0
        async for rec in self.hub.outputs():
            seen.add(rec["id"])
            sig = signature(rec)
            if known.get(rec["id"]) != sig:
                self.store.queue(rec, sig)
                queued += 1
        removed = 0
        for oid in set(known) - seen:
            removed += self.store.delete(oid)
        if queued:
            self.wake.set()
        log.info("library: %d outputs, %d to index, %d removed", len(seen), queued, removed)
        return {"outputs": len(seen), "queued": queued, "removed": removed}

    async def on_connect(self) -> None:
        self.connected = True
        try:
            await self.reconcile()
        except HubError as e:
            log.warning("library: couldn't list outputs: %s", e.detail)

    async def on_event(self, ev: dict[str, Any]) -> None:
        t = ev.get("type")
        if t == "output" and isinstance(ev.get("output"), dict):
            rec = ev["output"]
            self.store.queue(rec, signature(rec))       # the hub only announces outputs whose files changed
            self.wake.set()
        elif t == "output_deleted":
            if ev.get("id") == "*":                     # the hub re-read its folder: compare everything
                await self.reconcile()
            elif ev.get("id"):
                self.store.delete(ev["id"])

    def reindex(self, oid: str | None = None) -> int:
        """Queue one output, or all of them, again."""
        rows = [self.store.get(oid)] if oid else self.store.all()
        n = 0
        for r in rows:
            if r:
                self.store.queue(r, r["sig"])
                n += 1
        self.wake.set()
        return n

    # the indexing loop ----------------------------------------------------------------------

    async def run(self, stop: asyncio.Event) -> None:
        if not self.hub.url:
            self.state = "no_hub"
            return
        follower = asyncio.create_task(self.hub.follow(self.on_event, self.on_connect, stop))
        sampler = asyncio.create_task(self._sample(stop))
        try:
            while not stop.is_set():
                if not self.store.pending(1) and not self.store.chats_pending(1):
                    self.state = "idle"
                    await self._unload_if_unused()
                    self.wake.clear()
                    await self._wait(stop, 30)
                    continue
                if not self.gpu.idle():
                    self.state = "waiting_for_gpu"
                    await self._wait(stop, 5)
                    continue
                await self.drain()
                if self.state == "no_hub":
                    await self._wait(stop, 30)
        finally:
            follower.cancel()
            sampler.cancel()

    async def _sample(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            await asyncio.to_thread(self.gpu.sample)
            await asyncio.sleep(1)

    async def _wait(self, stop: asyncio.Event, s: float) -> None:
        waiters = [asyncio.create_task(stop.wait()), asyncio.create_task(self.wake.wait())]
        try:
            await asyncio.wait(waiters, timeout=s, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for w in waiters:
                w.cancel()

    async def drain(self) -> int:
        """Index pending outputs until the queue is empty, the GPU goes busy or there's no room. Returns how
        many were indexed."""
        n = 0
        self.state = "indexing"
        try:                                    # chat summaries first: few, cheap, and someone may be waiting (28.5)
            n += await self.index_chats()
        except Stop:
            self.state = "waiting_for_gpu"
            return n
        except HubError as e:
            if e.code == "needs_room":
                self.state = "no_room"
                return n
            raise
        while (rows := self.store.pending(1)):
            if self.store.chats_pending(1):      # summaries that came in meanwhile go before the next output
                try:
                    n += await self.index_chats()
                except Stop:
                    self.state = "waiting_for_gpu"
                    break
            row = rows[0]
            self.state, self.current = "indexing", {"id": row["id"], "title": row["title"], "kind": row["kind"]}
            try:
                await self.index_one(row)
                n += 1
                self.indexed += 1
            except Stop:
                self.state = "waiting_for_gpu"
                break
            except HubError as e:
                if e.code == "hub_unreachable":             # the hub went away: nothing to count against the output
                    self.state = "no_hub"
                    break
                if e.code == "needs_room":
                    self.state = "no_room"
                    self.gpu.quiet_since = self.gpu.clock()      # try again after another quiet period
                    break
                if e.status == 404:
                    self.store.delete(row["id"])
                else:
                    self.store.fail(row["id"], f"{e.code}: {e.detail}")
            except Exception as e:                  # noqa: BLE001: one bad output never stops the library
                log.warning("library: %s failed: %s", row["id"], e)
                self.store.fail(row["id"], f"{type(e).__name__}: {e}")
            finally:
                self.current = None
        if not self.store.pending(1) and not self.store.chats_pending(1):
            await self._unload_if_unused()
        return n

    async def index_chats(self, gate: bool = True, limit: int = 8) -> int:
        """Chat summaries (plan 28.5), a batch at a time; `gate=False` when someone is searching them."""
        GATED.set(gate)
        n = 0
        self._in_chats = True
        try:
            while (rows := self.store.chats_pending(limit)):
                vecs = await self._embed("text", [prompt(r["summary"], "document", r["title"]) for r in rows])
                for r, v in zip(rows, vecs):
                    self.store.finish_chat(r["thread_id"], r["summary"], v)
                n += len(rows)
        finally:
            self._in_chats = False
        return n

    async def _unload_if_unused(self) -> None:
        if self.enc.loaded and not self.enc.busy and time.time() - self.last_api > API_KEEP_S:
            log.info("library: queue empty, unloading")
            await asyncio.to_thread(self.enc.unload)

    async def _room(self, kinds: set[str]) -> None:
        """Ask the hub for the memory a load needs, without making room: background work never evicts."""
        want = self.enc.needs(kinds)
        if want is None:
            return
        have = self.enc.estimate_gb(self.enc.parts) if self.enc.loaded and self.enc.parts is not None else 0
        await self.hub.acquire(self.enc.estimate_gb(want) - have, f"indexing ({self.enc.key(want)})")

    async def _embed(self, kind: str, values: list[Any]) -> np.ndarray:
        """One batch, then a look at the GPU: someone else's work stops indexing here."""
        await self._room({kind})
        batch = {"text": self.s.index_batch_text, "image": self.s.batch_media, "audio": 1, "video": 1}
        vecs = await asyncio.to_thread(self.enc.embed, [(kind, v) for v in values], 768, batch)
        if GATED.get():
            await self.sleep(self.s.index_gap_s)
            if await asyncio.to_thread(self.gpu.busy_now):
                raise Stop()
        if not self._in_chats and self.store.chats_pending(1):     # summaries go between an output's batches too
            await self.index_chats(gate=GATED.get())
        return vecs

    async def index_one(self, row: dict[str, Any], gate: bool = True) -> None:
        """`gate=False`: someone is waiting for this output (a scoped search), so no look at the GPU between
        batches. Each asyncio task has its own context, so background indexing keeps its gate."""
        GATED.set(gate)
        rec = await self.hub.record(row["id"])
        kind = rec.get("kind")
        title = str(rec.get("title") or "")
        out: list[Chunk] = []
        if text := meta_text(rec):
            v = await self._embed("text", [prompt(text, "document", None)])
            out.append(Chunk("meta", v[0], chunking.snippet(text)))
        if kind in ("text", "document"):
            out += await self._text(rec["id"], title)
        elif kind in ("image", "model3d"):
            out += await self._image(rec, preview=kind == "model3d")
        elif kind == "video":
            out += await self._media(rec, "video")
        elif kind == "audio":
            out += await self._media(rec, "audio")
        # against the sig it was queued with: an event that changed it meanwhile leaves it pending
        self.store.finish(rec["id"], out, "done" if out else "skipped", sig=row["sig"])

    async def _text(self, oid: str, title: str) -> list[Chunk]:
        try:
            first = await self.hub.text(oid)
        except HubError as e:
            if e.code in ("not_text", "no_page"):
                return []
            raise
        parts, w = [first["text"]], first
        while w.get("next_offset") is not None:
            w = await self.hub.text(oid, offset=w["next_offset"])
            parts.append(w["text"])
        text = "".join(parts)
        starts = [(await self.hub.text(oid, limit=1, pages=str(p)))["offset"] for p in range(1, (first.get("pages") or 0) + 1)]
        pieces = chunking.chunk(text, starts or None)
        out: list[Chunk] = []
        for i in range(0, len(pieces), self.s.index_batch_text):
            group = pieces[i:i + self.s.index_batch_text]
            vecs = await self._embed("text", [prompt(p.text, "document", title) for p in group])
            out += [Chunk("text", v, chunking.snippet(p.text), text=p.text, page=p.page, line=p.line, offset=p.offset)
                    for p, v in zip(group, vecs)]
        return out

    async def _bytes(self, rec: dict[str, Any], kind: str, preview: bool = False) -> bytes | None:
        if preview and not rec.get("preview"):
            return None
        if not preview and (rec.get("size_bytes") or 0) > MAX_BYTES[kind]:
            log.info("library: %s is too large to embed (%s bytes); its title is indexed", rec["id"], rec.get("size_bytes"))
            return None
        return await self.hub.file(rec["id"], preview=preview)

    async def _image(self, rec: dict[str, Any], preview: bool) -> list[Chunk]:
        data = await self._bytes(rec, "model3d" if preview else "image", preview)
        if data is None:
            return []
        p = await asyncio.to_thread(media.image, data)
        v = await self._embed("image", [p.value])
        return [Chunk("image", v[0], "the 3D model's preview" if preview else "")]

    async def _media(self, rec: dict[str, Any], kind: str) -> list[Chunk]:
        data = await self._bytes(rec, kind)
        if data is None:
            return []
        if kind == "video":
            p = await asyncio.to_thread(media.video, data, self.s.video_max_frames, self.tmp)
            v = await self._embed("video", [p.value])
            return [Chunk("video", v[0], f"{p.info.get('frames')} frames", start_s=0, end_s=p.info.get("seconds"))]
        p = await asyncio.to_thread(media.audio, data, self.s.index_audio_max_s, self.tmp)
        secs = p.info["seconds"]
        whole = media.Prepared("audio", {"array": p.value["array"][: int(self.s.audio_max_s * media.SAMPLE_RATE)],
                                         "sampling_rate": media.SAMPLE_RATE})
        v = await self._embed("audio", [whole.value])
        out = [Chunk("audio", v[0], "the whole clip", start_s=0, end_s=min(secs, self.s.audio_max_s))]
        if secs > LONG_AUDIO_S:
            for a, b, w in media.windows(p):
                v = await self._embed("audio", [w.value])
                out.append(Chunk("audio", v[0], f"{a:.0f}–{b:.0f} s", start_s=a, end_s=b))
        return out

    # status ---------------------------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        return {"state": self.state, "connected": self.connected, "counts": self.store.counts(), "chats": self.store.chat_counts(),
                "current": self.current, "indexed_since_start": self.indexed,
                "gpu": {"measure": getattr(self.gpu.read, "measure", "device"), "busy_pct": self.gpu.last,
                        "detail": getattr(self.gpu.read, "detail", {}),
                        "quiet_s": self.gpu.quiet_s(), "idle": self.gpu.idle(),
                        "threshold_pct": self.gpu.busy_pct, "needs_quiet_s": self.gpu.idle_s}}


def open_library(settings: Settings, enc: Encoder, hub: Hub) -> Library:
    return Library(Store(Path(settings.databases) / "embed.db"), enc, hub, settings)

