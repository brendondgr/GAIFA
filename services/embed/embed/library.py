"""The library (plan 28.2): every output in GAIFA, indexed for search by meaning.

It follows the hub over HTTP: `GET /api/outputs` on every (re)connect to `/api/events` (new, changed and deleted
outputs since the last look), then `output` and `output_deleted` events. Each output becomes chunks in
`embed.db` (except hidden outputs, the web mod's saved pages: they aren't the user's, plan 30.9; one that
becomes hidden is dropped): a `meta` chunk from its title and prompt for every output; text and documents through the hub's text
route (24.3), in ~800-token chunks that keep page and line; an image (a 3D model's preview); a video whole; audio
whole plus 30 s windows when it's long.

Indexing waits for the GPU (plan 31.3): each batch takes a `background` lease from GAIFA's GPU queue, which the
hub grants only when no other mod's GPU work runs or waits, so indexing yields to anything else between batches
(state `waiting_gpu`, with what runs before it). A lease cancelled from the queue pauses indexing for a minute. It
unloads the model when the queue is empty (unless a search used it in the last minute). Loading for indexing
never evicts another mod: a 409 from the hub's memory acquire waits a minute.
"""

from __future__ import annotations

import asyncio
import contextvars
import hashlib
import json
import logging
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

from . import chunks as chunking
from . import media
from .encoder import Encoder, prompt
from .gpu import slot_for, take
from .gpu_slot import GpuCancelled, GpuSlot, Lease
from .hubclient import Hub, HubError
from .settings import Settings
from .store import Chunk, Store
from .worker import WorkerDied

log = logging.getLogger("embed")
MAX_BYTES = {"image": 64_000_000, "audio": 512_000_000, "video": 2_000_000_000, "model3d": 64_000_000}
LONG_AUDIO_S = 60
API_KEEP_S = 60            # a search in the last minute keeps the model loaded after indexing
BACKOFF_S = (30, 600)      # after an encoder error the loop waits 30 s, doubling to 10 min while it repeats
PAUSE_S = 60               # after a cancel from the GPU queue, or no room to load
GATED = contextvars.ContextVar("gated", default=True)    # False while a search indexes its own outputs (28.3)


class Stop(Exception):
    """The batch's GPU lease was cancelled from the queue: leave the output pending and try again later."""


def not_the_outputs_fault(e: BaseException) -> bool:
    """Errors that say nothing about the output being indexed, so they don't count as its failed attempt: the
    encoder's worker died while idle or loading, no weights, no room to load, the hub went away, the lease was cancelled."""
    if isinstance(e, Stop):
        return True
    if isinstance(e, WorkerDied):
        return e.stage != "call"
    if isinstance(e, HubError):
        return e.code in ("needs_room", "hub_unreachable")
    return isinstance(e, (FileNotFoundError, BrokenPipeError))


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
    def __init__(self, store: Store, enc: Encoder, hub: Hub, settings: Settings, gpu: GpuSlot | None = None,
                 sleep: Callable[[float], Any] = asyncio.sleep):
        self.store, self.enc, self.hub, self.s = store, enc, hub, settings
        self.gpu = gpu or slot_for(hub)
        self.gpu_wait: dict[str, Any] | None = None    # while a batch's lease waits: {ahead, eta_s}
        self.sleep = sleep
        self.tmp = settings.state_dir / "tmp"
        self.wake = asyncio.Event()
        self.state = "starting"            # starting | idle | waiting_gpu | indexing | paused | no_room | no_hub | error
        self.error: str | None = None      # the encoder error that stopped indexing (state `error`), until it works again
        self.backoff = BACKOFF_S[0]
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
            if rec.get("hidden"):                       # the hub leaves them out; an older hub may not
                continue
            seen.add(rec["id"])
            sig = signature(rec)
            if known.get(rec["id"]) != sig:
                self.store.queue(rec, sig)
                queued += 1
        removed = 0
        for oid in set(known) - seen:
            removed += self.store.delete(oid)
        if orphans := self.store.drop_orphans():
            log.info("library: dropped %d chunks of deleted outputs", orphans)
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
            if rec.get("hidden"):                       # not the user's (a saved web page): never indexed
                if rec.get("id"):
                    self.store.delete(rec["id"])
                return
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
        try:
            while not stop.is_set():
                if not self.store.pending(1) and not self.store.chats_pending(1):
                    self.state, self.error = "idle", None
                    await self._unload_if_unused()
                    self.wake.clear()
                    await self._wait(stop, 30)
                    continue
                try:
                    await self.drain()
                except Exception as e:              # noqa: BLE001: nothing ends the loop (or the follower with it)
                    log.exception("library: indexing stopped")
                    self._trouble(e)
                if self.state == "no_hub":                 # new outputs don't cut these waits short: they'd fail too
                    await self._wait(stop, 30, wake=False)
                elif self.state in ("paused", "no_room"):
                    await self._wait(stop, PAUSE_S, wake=False)
                elif self.state == "error":
                    await self._wait(stop, self.backoff, wake=False)
                    self.backoff = min(self.backoff * 2, BACKOFF_S[1])
        finally:
            follower.cancel()

    async def _wait(self, stop: asyncio.Event, s: float, wake: bool = True) -> None:
        waiters = [asyncio.create_task(stop.wait())] + ([asyncio.create_task(self.wake.wait())] if wake else [])
        try:
            await asyncio.wait(waiters, timeout=s, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for w in waiters:
                w.cancel()

    def _trouble(self, e: BaseException) -> None:
        """Indexing can't go on now (the encoder failed, or something unexpected): say why, and `run` backs off."""
        self.state, self.error = "error", f"{type(e).__name__}: {e}"[:500]

    def _stopped(self, e: BaseException) -> bool:
        """Drain's answer to an error from a step: True when indexing should stop now (the state says why)."""
        if isinstance(e, Stop):
            self.state = "paused"                         # cancelled from the GPU queue: try again in a minute
        elif isinstance(e, HubError) and e.code == "hub_unreachable":
            self.state = "no_hub"
        elif isinstance(e, HubError) and e.code == "needs_room":
            self.state = "no_room"
        elif not_the_outputs_fault(e) or isinstance(e, WorkerDied):
            log.warning("library: the encoder failed: %s", e)
            self._trouble(e)
        else:
            return False
        return True

    async def _chats(self) -> int | None:
        """Chat summaries, or None when indexing should stop (a summary has no attempts to count)."""
        try:
            n = await self.index_chats()
            if n:
                self.error, self.backoff = None, BACKOFF_S[0]
            return n
        except Exception as e:                      # noqa: BLE001: never ends the loop
            if not self._stopped(e):
                log.warning("library: chat summaries failed: %s", e)
                self._trouble(e)
            return None

    async def drain(self) -> int:
        """Index pending outputs until the queue is empty, the GPU goes busy or there's no room. Returns how
        many were indexed."""
        n = 0
        self.state = "indexing"
        done = await self._chats()              # chat summaries first: few, cheap, and someone may be waiting (28.5)
        if done is None:
            return n
        n += done
        while (rows := self.store.pending(1)):
            if self.store.chats_pending(1):      # summaries that came in meanwhile go before the next output
                if (done := await self._chats()) is None:
                    break
                n += done
            row = rows[0]
            self.state, self.current = "indexing", {"id": row["id"], "title": row["title"], "kind": row["kind"]}
            try:
                await self.index_one(row)
                n += 1
                self.indexed += 1
                self.error, self.backoff = None, BACKOFF_S[0]
            except Exception as e:                  # noqa: BLE001: one bad output never stops the library
                if isinstance(e, HubError) and e.status == 404:     # the output is gone
                    self.store.delete(row["id"])
                    continue
                if self.fail(row["id"], e):          # a worker that died on its inputs counts too: they may be the cause
                    log.warning("library: %s failed: %s", row["id"], e)
                if self._stopped(e):
                    break
            finally:
                self.current = None
        if not self.store.pending(1) and not self.store.chats_pending(1):
            await self._unload_if_unused()
        return n

    def fail(self, oid: str, e: BaseException) -> bool:
        """Count a failed attempt at an output, unless the error isn't the output's fault. Returns whether it counted."""
        if not_the_outputs_fault(e):
            return False
        self.store.fail(oid, f"{e.code}: {e.detail}" if isinstance(e, HubError) else f"{type(e).__name__}: {e}")
        return True

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

    async def encode(self, items: list[tuple[str, Any]], dim: int = 768, batch: dict[str, int] | None = None,
                     label: str = "Search") -> np.ndarray:
        """Someone is waiting for these vectors (a search): one `interactive` lease around the encode."""
        try:
            async with take(self.gpu, self.enc, self.s.device, label):
                return await asyncio.to_thread(self.enc.embed, items, dim, batch or {"text": 32})
        except GpuCancelled as e:
            raise HubError(409, str(e), "gpu_cancelled", fix="search again") from e

    def _on_wait(self, lease: Lease) -> None:
        self.state, self.gpu_wait = "waiting_gpu", {"ahead": lease.ahead, "eta_s": lease.eta_s}

    async def _embed(self, kind: str, values: list[Any]) -> np.ndarray:
        """One batch under its own GPU lease: `background` while indexing (it waits for everything else), and
        `interactive` while someone waits for the result (a scoped search, GATED off). Slot first, then memory."""
        gated = GATED.get()
        what = (self.current or {}).get("title") or ("chat summaries" if self._in_chats else "outputs")
        batch = {"text": self.s.index_batch_text, "image": self.s.batch_media, "audio": 1, "video": 1}
        try:
            async with take(self.gpu, self.enc, self.s.device, f"Indexing {str(what)[:60]}",
                            cls="background" if gated else "interactive", on_wait=self._on_wait if gated else None):
                if gated and self.gpu_wait is not None:
                    self.state = "indexing"
                self.gpu_wait = None
                await self._room({kind})
                vecs = await asyncio.to_thread(self.enc.embed, [(kind, v) for v in values], 768, batch)
        except GpuCancelled as e:
            raise Stop() from e
        finally:
            if gated:
                self.gpu_wait = None
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
        return {"state": self.state, "error": self.error, "connected": self.connected, "counts": self.store.counts(), "chats": self.store.chat_counts(),
                "current": self.current, "indexed_since_start": self.indexed,
                "gpu": {"class": "background", "waiting": self.gpu_wait is not None,
                        "ahead": (self.gpu_wait or {}).get("ahead") or [], "eta_s": (self.gpu_wait or {}).get("eta_s")}}

    def job(self) -> dict[str, Any] | None:
        """The library as a job in `/v1/status` while it indexes or waits for the GPU (`stage: waiting_gpu`)."""
        if self.state not in ("indexing", "waiting_gpu"):
            return None
        c = self.store.counts()
        job: dict[str, Any] = {"id": "library", "label": f"Indexing outputs ({c['pending']} to go)",
                               "state": "running" if self.state == "indexing" else "queued",
                               "progress": round(c["done"] / max(1, c["done"] + c["pending"]), 3), "route": "#/s/embed"}
        if self.state == "waiting_gpu":
            job.update(stage="waiting_gpu", ahead=(self.gpu_wait or {}).get("ahead") or [],
                       eta_s=(self.gpu_wait or {}).get("eta_s"))
        return job


def open_library(settings: Settings, enc: Encoder, hub: Hub) -> Library:
    return Library(Store(Path(settings.databases) / "embed.db"), enc, hub, settings)

