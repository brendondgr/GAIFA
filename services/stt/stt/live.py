"""`WS /v1/stream`: live transcription with the prototype's streaming engine (plan 29.2).

The protocol, in order:

1. client → ``{"type": "start", "preset"?, "model"?, "language"?, "encoding"?: "int16" | "float32",
   "sample_rate"?: 16000, "save"?: false, "title"?}``; server → ``{"type": "ready", "model", "device",
   "precision", "sample_rate": 16000, "reason"?}`` once the model is loaded. ``reason`` says why it runs on
   the CPU ("on the CPU: Images & Video (portrait) is using the GPU").
2. client → binary frames: mono PCM, little-endian, at ``sample_rate`` (16 kHz is what the engine
   runs at; anything else is resampled here). Any frame size.
3. server → ``{"type": "committed", "segment": {id, start, end, text}}`` for text that will never
   change, and ``{"type": "hypothesis", "text", "start"}`` for the tail, which replaces the last one
   (empty text clears it). ``{"type": "notice", "code", "message"}`` for anything worth saying.
4. client → ``{"type": "stop"}``; the server flushes, sends the last committed segments, then
   ``{"type": "done", "text", "duration", "language", "segments", "output"?}`` and closes (1000).

Errors arrive as ``{"type": "error", "detail", "code"}`` followed by a close (4400 for a protocol
mistake, 4409 ``busy`` when a file job or another stream is using a different model, 4500 when the
model fails). An open stream holds a lease on its model: the idle unloader leaves it loaded through
any silence, and if it is unloaded anyway (``POST /v1/unload``) the next pass loads it again.

**The GPU slot (plan 31.3; ``gpu.py``).** Dictation never waits for the GPU. When another mod's work holds
GAIFA's GPU slot at the start, the stream runs on the CPU (its own CPU model, ``small`` at most). Otherwise it
holds an ``interactive`` lease while it runs on the GPU, and when another mod's work starts waiting, it loads
the CPU model, moves to it between two frames and gives the slot back: ``{"type": "device", "device": "cpu",
"model", "precision", "reason"}`` tells the client.

Commits follow LocalAgreement-2: a word is committed once two passes agree on it, so committed text
trails the speaker by about one to two seconds.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
import uuid
from typing import Any

import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from . import catalog, transcripts
from .audio.decode import DecodeError, pcm_frame
from .audio.formats import SAMPLE_RATE
from .audio.resample import resample
from .config import StreamingConfig, VadConfig
from .engine import Engine, ModelBusy
from .gpu import Gpu, holder_text
from .segment import Segment
from .streaming import CommittedSegment, EngineNotice, HypothesisUpdate, StreamingEngine
from .vad import build_gate

logger = logging.getLogger(__name__)

FRAME = 512                    # 32 ms at 16 kHz: what the speech gate is tuned for
MAX_SECONDS = 4 * 3600         # one stream
WATCH_S = 2.0                  # how often a stream on the GPU asks whether another mod's work waits
GPU_WAIT_S = 1.0               # a stream that isn't given the slot this fast runs on the CPU
CPU_MAX = "small"              # the largest model live dictation runs on the CPU


class ProtocolError(ValueError):
    pass


class LiveSession:
    """One stream: frames in, events out. ``feed`` and ``finish`` block; run them in a thread."""

    def __init__(self, engine: Engine, *, model: str, language: str | None, sample_rate: int) -> None:
        self.engine, self.model, self.language, self.rate = engine, model, language, sample_rate
        self.stream = StreamingEngine(StreamingConfig(), transcribe=self._pass,
                                      capabilities=engine.capabilities, model_id=engine.model_id)
        self.gate = build_gate(VadConfig())
        self.pending = np.zeros(0, dtype=np.float32)
        self.segments: list[Segment] = []
        self.seconds = 0.0

    def _pass(self, audio: np.ndarray, prompt: str | None = None):
        return self.engine.transcribe(audio, prompt, language=self.language, model=self.model)

    def switch(self, engine: Engine, model: str) -> None:
        """Run the next passes on another engine (between two ``feed`` calls)."""
        self.engine, self.model = engine, model
        self.stream.set_model(engine.model_id, engine.capabilities)

    def feed(self, samples: np.ndarray) -> list[dict[str, Any]]:
        if self.rate != SAMPLE_RATE:
            samples = resample(samples, self.rate, SAMPLE_RATE)
        self.pending = np.concatenate([self.pending, samples])
        events: list[dict[str, Any]] = []
        whole = self.pending.size // FRAME * FRAME
        for start in range(0, whole, FRAME):
            frame = self.pending[start:start + FRAME]
            vad = self.gate.process(frame)
            events += self._out(self.stream.add_audio(frame, speaking=vad.speaking, pause=vad.pause_event))
        self.pending = self.pending[whole:]
        self.seconds += samples.size / SAMPLE_RATE
        return events

    def finish(self) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        if self.pending.size:
            events += self._out(self.stream.add_audio(self.pending, speaking=True))
            self.pending = np.zeros(0, dtype=np.float32)
        return events + self._out(self.stream.flush())

    def _out(self, engine_events: list) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for ev in engine_events:
            if isinstance(ev, CommittedSegment):
                self.segments.append(ev.segment)
                s = ev.segment
                out.append({"type": "committed", "segment": {"id": s.id, "start": round(s.start, 2),
                                                             "end": round(s.end, 2), "text": s.text}})
            elif isinstance(ev, HypothesisUpdate):
                out.append({"type": "hypothesis", "text": ev.text, "start": round(ev.start, 2)})
            elif isinstance(ev, EngineNotice):
                out.append({"type": "notice", "code": ev.code, "message": ev.message})
        return out


def cpu_model_for(model: str) -> str:
    """The model a stream runs on the CPU: the one asked for, at most ``CPU_MAX``."""
    names = list(catalog.BY_NAME)
    return model if names.index(model) <= names.index(CPU_MAX) else CPU_MAX


async def _acquire_cpu(cpu_engine: Engine, model: str) -> str:
    """Lease a CPU model; when another stream holds a different one there, share that one."""
    try:
        await cpu_engine.acquire(model)
        return model
    except ModelBusy as exc:
        other = sorted(exc.held)[0]
        await cpu_engine.acquire(other)
        return other


def mount(app: FastAPI, engine: Engine, cpu_engine: Engine | None = None, gpu: Gpu | None = None) -> None:
    settings = app.state.settings
    if not hasattr(app.state, "streams"):
        app.state.streams = {}
    streams: dict[str, dict[str, Any]] = app.state.streams

    async def choose(model: str, stack: contextlib.AsyncExitStack) -> tuple[Engine, str, str | None, bool]:
        """(engine, model, why it runs on the CPU, holds the GPU slot)."""
        if cpu_engine is None or gpu is None or not gpu.enabled or engine.fell_back or not await engine.gpu():
            return engine, model, None, False
        other = await gpu.other()
        if other is None:
            lease = await gpu.enter(stack, "Live dictation", cls="interactive", timeout=GPU_WAIT_S)
            if lease is not None:
                return engine, model, None, lease.state == "granted"
            other = await gpu.other()
        return cpu_engine, cpu_model_for(model), f"on the CPU: {holder_text(other)}", False

    async def watch(state: dict[str, Any]) -> None:
        """While the stream holds the slot: when another mod's work waits, load the CPU model and ask the
        stream to move to it (the GPU keeps serving until then)."""
        assert gpu is not None and cpu_engine is not None
        while True:
            await asyncio.sleep(WATCH_S)
            other = await gpu.other()
            if other is None:
                continue
            try:
                cpu_model = await _acquire_cpu(cpu_engine, cpu_model_for(state["model"]))
            except Exception:  # noqa: BLE001 - stay on the GPU; the other work waits for the stream
                logger.exception("Couldn't load the CPU model to give the GPU back")
                return
            state["leases"].append((cpu_engine, cpu_model))
            state["switch"] = (cpu_model, f"on the CPU: {holder_text(other)}")
            return

    @app.websocket("/v1/stream")
    async def stream(ws: WebSocket) -> None:
        await ws.accept()
        session: LiveSession | None = None
        sid = uuid.uuid4().hex[:8]
        state: dict[str, Any] = {"leases": [], "switch": None, "model": None}
        gpu_stack = contextlib.AsyncExitStack()
        watcher: asyncio.Task | None = None
        try:
            first = await ws.receive()
            if first["type"] == "websocket.disconnect":
                return
            try:
                start = json.loads(first.get("text") or "")
            except ValueError:
                start = None
            if not isinstance(start, dict) or start.get("type") != "start":
                raise ProtocolError('send {"type": "start"} first')
            encoding = start.get("encoding") or "int16"
            if encoding not in ("int16", "float32"):
                raise ProtocolError("encoding must be int16 or float32")
            rate = int(start.get("sample_rate") or SAMPLE_RATE)
            if not 8000 <= rate <= 192000:
                raise ProtocolError("sample_rate must be between 8000 and 192000")
            try:
                model = catalog.pick(start.get("model"), start.get("preset"))
            except catalog.UnknownModel as exc:
                raise ProtocolError(str(exc)) from exc
            eng, model, why, held = await choose(model, gpu_stack)
            try:
                if eng is cpu_engine:
                    model = await _acquire_cpu(eng, model)
                else:
                    await eng.acquire(model)
            except ModelBusy as exc:
                await _fail(ws, f"{exc}; {exc.fix}", "busy", 4409)
                return
            except Exception as exc:  # noqa: BLE001
                await _fail(ws, f"couldn't load {model}: {exc}", "load_failed", 4500)
                return
            state["leases"].append((eng, model))
            state["model"] = model
            session = LiveSession(eng, model=model, language=start.get("language") or None, sample_rate=rate)
            streams[sid] = {"id": sid, "model": model, "device": eng.device, "gpu_slot": held,
                            **({"reason": why} if why else {})}
            await ws.send_json({"type": "ready", "model": model, "device": eng.device,
                                "precision": eng.precision, "sample_rate": SAMPLE_RATE, **({"reason": why} if why else {})})
            if held:
                watcher = asyncio.create_task(watch(state))
            while True:
                msg = await ws.receive()
                if msg["type"] == "websocket.disconnect":
                    return
                if state["switch"] is not None:                 # between two frames: no pass is running
                    cpu_model, reason = state["switch"]
                    state["switch"] = None
                    old = (session.engine, session.model)
                    session.switch(cpu_engine, cpu_model)
                    state["leases"].remove(old)
                    old[0].release(old[1])
                    await gpu_stack.aclose()                    # the slot goes back
                    streams[sid] = {"id": sid, "model": cpu_model, "device": cpu_engine.device, "gpu_slot": False,
                                    "reason": reason}
                    await ws.send_json({"type": "device", "device": cpu_engine.device, "model": cpu_model,
                                        "precision": cpu_engine.precision, "reason": reason})
                if msg.get("bytes") is not None:
                    try:
                        samples = pcm_frame(msg["bytes"], encoding)
                    except DecodeError as exc:
                        raise ProtocolError(str(exc)) from exc
                    if session.seconds > MAX_SECONDS:
                        raise ProtocolError("a stream is limited to four hours")
                    for event in await asyncio.to_thread(session.feed, samples):
                        await ws.send_json(event)
                    continue
                try:
                    stop = json.loads(msg.get("text") or "")
                except ValueError:
                    stop = None
                if not isinstance(stop, dict) or stop.get("type") != "stop":
                    raise ProtocolError('only audio frames and {"type": "stop"} may follow "start"')
                for event in await asyncio.to_thread(session.finish):
                    await ws.send_json(event)
                await ws.send_json(await _done(session, start, settings))
                await ws.close(code=1000)
                return
        except ProtocolError as exc:
            await _fail(ws, str(exc), "invalid_input", 4400)
        except WebSocketDisconnect:
            return
        except Exception as exc:  # noqa: BLE001 - the client hears what happened
            logger.exception("Live stream failed")
            await _fail(ws, str(exc) or type(exc).__name__, "stream_failed", 4500)
        finally:
            if watcher is not None:
                watcher.cancel()
                await asyncio.gather(watcher, return_exceptions=True)
            for eng, leased in state["leases"]:
                eng.release(leased)
            await gpu_stack.aclose()
            streams.pop(sid, None)


async def _done(session: LiveSession, start: dict, settings) -> dict[str, Any]:
    language = session.language or session.engine.last_language
    res = transcripts.result(session.segments, duration=session.seconds, language=language, model=session.model)
    if start.get("save"):
        title = str(start.get("title") or "dictation")[:80]
        folder = await asyncio.to_thread(transcripts.save, settings.outputs, session.segments, res, title=title,
                                         source={"service": "stt", "live": True}, now=time.time())
        res["output"] = f"stt/{folder.relative_to(settings.outputs).as_posix()}"
    return {"type": "done", **res}


async def _fail(ws: WebSocket, detail: str, code: str, close: int) -> None:
    with contextlib.suppress(Exception):
        await ws.send_json({"type": "error", "detail": detail, "code": code})
        await ws.close(code=close, reason=detail[:120])
