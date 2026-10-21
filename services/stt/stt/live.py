"""`WS /v1/stream`: live transcription with the prototype's streaming engine (plan 29.2).

The protocol, in order:

1. client → ``{"type": "start", "preset"?, "model"?, "language"?, "encoding"?: "int16" | "float32",
   "sample_rate"?: 16000, "save"?: false, "title"?}``; server → ``{"type": "ready", "model", "device",
   "precision", "sample_rate": 16000}`` once the model is loaded.
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

Commits follow LocalAgreement-2: a word is committed once two passes agree on it, so committed text
trails the speaker by about one to two seconds.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from functools import partial
from typing import Any

import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from . import catalog, transcripts
from .audio.decode import DecodeError, pcm_frame
from .audio.formats import SAMPLE_RATE
from .audio.resample import resample
from .config import StreamingConfig, VadConfig
from .engine import Engine, ModelBusy
from .segment import Segment
from .streaming import CommittedSegment, EngineNotice, HypothesisUpdate, StreamingEngine
from .vad import build_gate

logger = logging.getLogger(__name__)

FRAME = 512                    # 32 ms at 16 kHz: what the speech gate is tuned for
MAX_SECONDS = 4 * 3600         # one stream


class ProtocolError(ValueError):
    pass


class LiveSession:
    """One stream: frames in, events out. ``feed`` and ``finish`` block; run them in a thread."""

    def __init__(self, engine: Engine, *, model: str, language: str | None, sample_rate: int) -> None:
        self.engine, self.model, self.language, self.rate = engine, model, language, sample_rate
        transcribe = partial(engine.transcribe, language=language, model=model)
        self.stream = StreamingEngine(StreamingConfig(), transcribe=transcribe,
                                      capabilities=engine.capabilities, model_id=engine.model_id)
        self.gate = build_gate(VadConfig())
        self.pending = np.zeros(0, dtype=np.float32)
        self.segments: list[Segment] = []
        self.seconds = 0.0

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


def mount(app: FastAPI, engine: Engine) -> None:
    settings = app.state.settings

    @app.websocket("/v1/stream")
    async def stream(ws: WebSocket) -> None:
        await ws.accept()
        session: LiveSession | None = None
        leased: str | None = None
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
            try:
                await engine.acquire(model)
            except ModelBusy as exc:
                await _fail(ws, f"{exc}; {exc.fix}", "busy", 4409)
                return
            except Exception as exc:  # noqa: BLE001
                await _fail(ws, f"couldn't load {model}: {exc}", "load_failed", 4500)
                return
            leased = model
            session = LiveSession(engine, model=model, language=start.get("language") or None, sample_rate=rate)
            await ws.send_json({"type": "ready", "model": model, "device": engine.device,
                                "precision": engine.precision, "sample_rate": SAMPLE_RATE})
            while True:
                msg = await ws.receive()
                if msg["type"] == "websocket.disconnect":
                    return
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
            if leased is not None:
                engine.release(leased)


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
