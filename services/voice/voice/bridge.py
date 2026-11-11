"""The realtime bridge: the page's WebSocket on one side, llama.cpp's /v1/realtime on the other.

The page speaks a small protocol of this mod's own, so it never depends on llama.cpp's schema.

    page → mod   {"type":"start", "thread"?, "voice"?, "language"?, "pause_ms"?, "sample_rate"?}
                 binary frames: PCM16 mono at sample_rate (16000 unless said)
                 {"type":"text", "text"}            a typed turn (the mod's page, the eval)
                 {"type":"interrupt", "played_ms"}  you started talking over the reply
                 {"type":"played"}                  the reply finished playing
                 {"type":"stop"}
    mod → page   {"type":"waiting", "text"}         the GPU is busy with something else
                 {"type":"ready", "sample_rate_out", "model", "voice"}
                 {"type":"listening"} · {"type":"hearing"} · {"type":"thinking"} · {"type":"speaking"}
                 binary frames: the reply, PCM16 mono at sample_rate_out
                 {"type":"said", "text", "final", "audio_ms"?}     the reply's text as it comes
                 {"type":"heard", "text"}           your turn as text
                 {"type":"turn", "user", "assistant", "first_audio_ms", "interrupted", "saved"}
                 {"type":"error", "code", "detail", "fix"?}
                 {"type":"done"}
    close codes  4400 a bad start · 4409 busy · 4500 the engine failed

One conversation at a time. Beside it runs a second llama.cpp session of type "transcription", fed the same
audio, which writes your words down (a conversation session doesn't). A turn is written into the chat (the
agent's /voice-turn, through the hub) once its reply has played, or as far as it played when you interrupt.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
import time
from collections import deque
from typing import Any

import websockets
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field, ValidationError

from . import config, vad
from .engine import EngineError
from .gpu_slot import GpuCancelled, gpu_slot
from .hub import HubError

log = logging.getLogger(__name__)

BASE_INSTRUCTIONS = "Respond with interleaved text and audio."
SPOKEN_STYLE = ("You are talking with the user out loud. Keep answers short and natural, as in a conversation; "
                "no lists, markdown or code.")
RENEW_TOKENS = 24000                      # of the 32,768 context: open a fresh session with the talk as text
HISTORY_CHARS = 24000                     # about 6,000 tokens of earlier turns
AUDIO_TOKENS_PER_S = 13                   # a rough count of what your speech costs the context
RESPONSE_TIMEOUT_S = 60.0
HOLD_MS = 600                             # microphone audio kept while the reply plays, for a barge-in's first words


class Start(BaseModel):
    type: str
    thread: str | None = Field(None, max_length=64)
    voice: str = "female"
    language: str | None = Field(None, pattern=r"^[a-z]{2,3}(-[A-Za-z]{2,4})?$")
    pause_ms: int = Field(1200, ge=300, le=5000)
    sample_rate: int = Field(16000, ge=8000, le=48000)
    save: bool = True                      # False: nothing is written into the chat (a test of the microphone)


def vad_kind(settings) -> str:
    return vad.vad_kind(settings.vad_model)


def transcript(turns: list[dict[str, str]], limit: int = HISTORY_CHARS) -> str:
    """Earlier turns as "User: … / Assistant: …" lines, the newest kept when they don't all fit."""
    lines: list[str] = []
    used = 0
    for t in reversed(turns):
        line = f"{'User' if t.get('role') == 'user' else 'Assistant'}: {' '.join(str(t.get('text') or '').split())}"
        if used + len(line) > limit:
            break
        lines.append(line)
        used += len(line) + 1
    return "\n".join(reversed(lines))


def instructions(context: dict[str, Any], turns: list[dict[str, str]]) -> str:
    parts = [BASE_INSTRUCTIONS, SPOKEN_STYLE]
    if context.get("instructions"):
        parts.append(str(context["instructions"]).strip())
    talk = transcript([*(context.get("history") or []), *turns])
    if talk:
        parts.append("The conversation so far:\n" + talk)
    return "\n\n".join(parts)


def heard_part(text: str, played_ms: float, audio_ms: float, complete: bool = True) -> str:
    """What of a reply you heard before interrupting it: the words in proportion to the audio played."""
    words = text.split()
    if not words:
        return ""
    if audio_ms <= 0 or played_ms >= audio_ms:
        return text.strip() + ("" if complete else "…")
    n = int(len(words) * max(0.0, played_ms) / audio_ms)
    return (" ".join(words[:n]) + "…") if n else ""


class Reply:
    def __init__(self) -> None:
        self.text = ""
        self.audio_bytes = 0
        self.first_audio_ms: int | None = None
        self.done = asyncio.Event()
        self.status = ""
        self.tokens = 0


class Session:
    def __init__(self, ws: WebSocket, app: FastAPI) -> None:
        self.ws = ws
        self.engine, self.hub, self.stats, self.settings = app.state.engine, app.state.hub, app.state.stats, app.state.settings
        self.start: Start | None = None
        self.context: dict[str, Any] = {}
        self.turns: list[dict[str, str]] = []          # this session's turns, for a renewed session
        self.conv = self.asr = None
        self.out_rate = 24000
        self.mode = "listening"
        self.detector: vad.TurnDetector | None = None
        self.hold: deque[bytes] = deque()
        self.hold_bytes = 0
        self.reply: Reply | None = None
        self.skip = False                              # drop upstream events of a cancelled reply until its done
        self.typed: str | None = None
        self.heard: asyncio.Future[str] | None = None
        self.t_end = 0.0
        self.spoke_s = 0.0
        self.tokens = 0
        self.send_lock = asyncio.Lock()
        self.closed = False

    # ---- to the page

    async def emit(self, type_: str, **data: Any) -> None:
        if self.closed:
            return
        with contextlib.suppress(Exception):
            async with self.send_lock:
                await self.ws.send_text(json.dumps({"type": type_, **data}))

    async def audio_out(self, pcm: bytes) -> None:
        if self.closed:
            return
        with contextlib.suppress(Exception):
            async with self.send_lock:
                await self.ws.send_bytes(pcm)

    async def set_mode(self, mode: str) -> None:
        if mode != self.mode:
            self.mode = mode
            await self.emit(mode)

    async def fail(self, code: int, err: str, detail: str, fix: str | None = None) -> None:
        await self.emit("error", code=err, detail=detail, **({"fix": fix} if fix else {}))
        self.closed = True
        with contextlib.suppress(Exception):
            await self.ws.close(code=code, reason=err)

    # ---- llama.cpp's sessions

    async def _open(self, port: int, session: dict[str, Any]):
        up = await websockets.connect(f"ws://127.0.0.1:{port}/v1/realtime", max_size=None, open_timeout=10)
        created = json.loads(await asyncio.wait_for(up.recv(), 10))
        if created.get("type") == "error":
            raise EngineError(502, created["error"].get("message", "llama.cpp refused the session"), "engine_failed")
        await up.send(json.dumps({"type": "session.update", "session": session}))
        updated = json.loads(await asyncio.wait_for(up.recv(), 10))
        if updated.get("type") == "error":
            raise EngineError(502, updated["error"].get("message", "llama.cpp refused the session"), "engine_failed")
        return up, updated.get("session") or {}

    async def open_conv(self, port: int) -> None:
        s = self.start
        out: dict[str, Any] = {"voice": s.voice}
        if s.language:
            out["language"] = s.language.split("-")[0]
        text = instructions(self.context, self.turns)
        self.conv, sess = await self._open(port, {
            "type": "realtime", "instructions": text, "output_modalities": ["text", "audio"],
            "audio": {"input": {"format": {"type": "audio/pcm", "rate": s.sample_rate}}, "output": out}})
        self.out_rate = ((sess.get("audio") or {}).get("output") or {}).get("format", {}).get("rate") or 24000
        self.tokens = len(text) // 4

    async def open_asr(self, port: int) -> None:
        s = self.start
        audio: dict[str, Any] = {"format": {"type": "audio/pcm", "rate": s.sample_rate}}
        if s.language:
            audio["transcription"] = {"language": s.language.split("-")[0]}
        self.asr, _ = await self._open(port, {"type": "transcription", "audio": {"input": audio}})

    async def up(self, sock, ev: dict[str, Any]) -> None:
        await sock.send(json.dumps(ev))

    # ---- your side

    async def on_audio(self, pcm: bytes) -> None:
        self.engine.touch()
        if self.mode in ("thinking", "speaking"):
            self.hold.append(pcm)
            self.hold_bytes += len(pcm)
            limit = self.start.sample_rate * 2 * HOLD_MS // 1000
            while self.hold_bytes > limit and len(self.hold) > 1:
                self.hold_bytes -= len(self.hold.popleft())
            return
        await self.on_detected(self.detector.feed(pcm))

    async def on_detected(self, events: list[tuple[str, bytes | None]]) -> None:
        for kind, data in events:
            if kind == "speech":
                await self.set_mode("hearing")
                self.spoke_s += len(data) / 2 / self.start.sample_rate
                ev = {"type": "input_audio_buffer.append", "audio": base64.b64encode(data).decode()}
                await self.up(self.conv, ev)
                await self.up(self.asr, ev)
            elif kind == "end":
                await self.end_turn()

    async def end_turn(self, typed: str | None = None) -> None:
        """Your turn is over: ask for the reply, and for your words as text."""
        self.reply, self.skip, self.typed = Reply(), False, typed
        self.t_end = time.monotonic()
        self.heard = asyncio.get_running_loop().create_future()
        if typed is None:
            await self.up(self.asr, {"type": "input_audio_buffer.commit"})
        else:
            self.heard.set_result(typed)
            await self.emit("heard", text=typed)
            await self.up(self.conv, {"type": "conversation.item.create", "item": {
                "type": "message", "role": "user", "content": [{"type": "input_text", "text": typed}]}})
        await self.up(self.conv, {"type": "response.create"})
        await self.set_mode("thinking")

    async def on_interrupt(self, played_ms: float) -> None:
        reply = self.reply
        if reply is None or self.mode not in ("thinking", "speaking"):
            return
        if not reply.done.is_set():
            self.skip = True
            await self.up(self.conv, {"type": "response.cancel"})
        held = b"".join(self.hold)
        await self.finish_turn(interrupted=True, played_ms=played_ms)
        await self.on_detected(self.detector.begin(held))

    async def on_played(self) -> None:
        if self.reply is not None and self.mode in ("thinking", "speaking"):
            await self.finish_turn(interrupted=False)

    async def finish_turn(self, interrupted: bool, played_ms: float = 0.0) -> None:
        """The reply is over for you: report the turn, write it into the chat, listen again."""
        reply, self.reply = self.reply, None
        self.hold.clear()
        self.hold_bytes = 0
        if not interrupted:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(reply.done.wait(), RESPONSE_TIMEOUT_S)
        user = ""
        with contextlib.suppress(TimeoutError, asyncio.CancelledError):
            user = (await asyncio.wait_for(asyncio.shield(self.heard), 5)).strip()
        audio_ms = reply.audio_bytes / 2 / self.out_rate * 1000
        said = heard_part(reply.text, played_ms, audio_ms, reply.done.is_set()) if interrupted else reply.text.strip()
        saved = False
        if user:
            self.turns += [{"role": "user", "text": user}, *([{"role": "assistant", "text": said}] if said else [])]
            self.stats.turn(reply.first_audio_ms)
            if self.start.thread and self.start.save:
                saved = await self.hub.voice_turn(self.start.thread, {
                    "user": user, "assistant": said, "model": config.MODEL_ID, "first_audio_ms": reply.first_audio_ms,
                    "interrupted": interrupted}) is not None
        await self.emit("turn", user=user, assistant=said, first_audio_ms=reply.first_audio_ms, interrupted=interrupted,
                        saved=saved)
        self.detector.reset()
        if self.tokens + self.spoke_s * AUDIO_TOKENS_PER_S > RENEW_TOKENS and not interrupted:
            await self.renew()
        await self.set_mode("listening")

    async def renew(self) -> None:
        """The context is nearly full: a fresh session that knows the talk so far as text."""
        log.info("renewing the session at about %d tokens", self.tokens + self.spoke_s * AUDIO_TOKENS_PER_S)
        old, self.conv = self.conv, None
        self._conv_task.cancel()
        with contextlib.suppress(Exception):
            await old.close()
        await self.open_conv(self.engine.port)
        self.spoke_s = 0.0
        self._conv_task = asyncio.create_task(self.read_conv())

    # ---- llama.cpp's side

    async def read_conv(self) -> None:
        async for raw in self.conv:
            ev = json.loads(raw)
            t = ev.get("type")
            reply = self.reply
            if t == "response.done":
                usage = (ev.get("response") or {}).get("usage") or {}
                self.tokens += int(usage.get("output_tokens") or 0)
                if self.skip:
                    self.skip = False
                    continue
                if reply is not None:
                    reply.status = (ev.get("response") or {}).get("status") or ""
                    reply.done.set()
                    await self.emit("said", text=reply.text, final=True,
                                    audio_ms=round(reply.audio_bytes / 2 / self.out_rate * 1000))
            elif self.skip or reply is None:
                continue
            elif t == "response.output_text.delta":
                reply.text += ev.get("delta") or ""
                await self.emit("said", text=reply.text, final=False)
            elif t == "response.output_audio.delta":
                pcm = base64.b64decode(ev.get("delta") or "")
                if reply.first_audio_ms is None:
                    reply.first_audio_ms = round((time.monotonic() - self.t_end) * 1000)
                    await self.set_mode("speaking")
                reply.audio_bytes += len(pcm)
                await self.audio_out(pcm)
            elif t == "error":
                detail = (ev.get("error") or {}).get("message") or "llama.cpp reported an error"
                log.warning("llama.cpp: %s", detail)
                await self.emit("error", code="engine_error", detail=detail)
                reply.done.set()

    async def read_asr(self) -> None:
        async for raw in self.asr:
            ev = json.loads(raw)
            if ev.get("type") == "conversation.item.input_audio_transcription.completed":
                text = (ev.get("transcript") or "").strip()
                if self.heard is not None and not self.heard.done():
                    self.heard.set_result(text)
                    if text:
                        await self.emit("heard", text=text)
            elif ev.get("type") == "error" and self.heard is not None and not self.heard.done():
                self.heard.set_result("")

    async def read_page(self) -> None:
        while True:
            msg = await self.ws.receive()
            if msg["type"] == "websocket.disconnect":
                return
            if msg.get("bytes") is not None:
                await self.on_audio(msg["bytes"])
                continue
            try:
                ev = json.loads(msg.get("text") or "")
            except ValueError:
                continue
            t = ev.get("type")
            if t == "stop":
                return
            if t == "interrupt":
                await self.on_interrupt(float(ev.get("played_ms") or 0))
            elif t == "played":
                await self.on_played()
            elif t == "text" and str(ev.get("text") or "").strip() and self.mode in ("listening", "hearing"):
                await self.end_turn(typed=str(ev["text"]).strip()[:4000])

    async def watchdog(self) -> None:
        """A reply that never finishes is cancelled, so the conversation isn't stuck."""
        while True:
            await asyncio.sleep(1)
            r = self.reply
            if r is not None and not r.done.is_set() and time.monotonic() - self.t_end > RESPONSE_TIMEOUT_S:
                log.warning("a reply took over %.0f s: cancelled", RESPONSE_TIMEOUT_S)
                with contextlib.suppress(Exception):
                    await self.up(self.conv, {"type": "response.cancel"})
                r.done.set()
                await self.emit("error", code="reply_timeout", detail="The reply took too long and was stopped.")
                await self.finish_turn(interrupted=True, played_ms=1e12)

    # ---- the whole conversation

    async def run(self) -> None:
        await self.ws.accept()
        try:
            self.start = Start.model_validate_json(await asyncio.wait_for(self.ws.receive_text(), 10))
            if self.start.type != "start" or self.start.voice not in config.VOICES:
                raise ValueError("the first message must be a start with voice female or male")
        except (ValidationError, ValueError, TimeoutError, KeyError, WebSocketDisconnect) as e:
            return await self.fail(4400, "bad_start", str(e).splitlines()[0] if str(e) else "no start message")
        if self.engine.sessions >= 1:
            return await self.fail(4409, "busy", "Another voice conversation is open.")
        self.engine.sessions += 1
        tasks: list[asyncio.Task] = []
        try:
            async def waiting(lease) -> None:
                await self.emit("waiting", text=lease.waiting_text())

            async with gpu_slot("Voice conversation", est_s=120, on_wait=waiting):
                try:
                    port = await self.engine.ensure()
                    if self.start.thread:
                        self.context = await self.hub.voice_context(self.start.thread)
                        if not self.start.language and self.context.get("language"):
                            self.start.language = self.context["language"]
                    await self.open_conv(port)
                    await self.open_asr(port)
                except (EngineError, HubError) as e:
                    return await self.fail(4409 if e.code in ("needs_room", "busy") else 4500, e.code, e.detail,
                                           getattr(e, "fix", None))
                except (OSError, websockets.WebSocketException, TimeoutError) as e:
                    return await self.fail(4500, "engine_failed", f"llama.cpp didn't open a session ({e})")
                self.detector = vad.TurnDetector(vad.make_vad(self.settings.vad_model), rate=self.start.sample_rate,
                                                 pause_ms=self.start.pause_ms)
                await self.emit("ready", sample_rate_out=self.out_rate, model=self.engine.status()["label"],
                                voice=self.start.voice, vad=self.detector.vad.kind)
                await self.emit("listening")
                self._conv_task = asyncio.create_task(self.read_conv())
                page = asyncio.create_task(self.read_page())
                tasks = [page, asyncio.create_task(self.read_asr()), asyncio.create_task(self.watchdog())]
                while True:
                    done, _ = await asyncio.wait([*tasks, self._conv_task], return_when=asyncio.FIRST_COMPLETED)
                    if page in done:
                        with contextlib.suppress(WebSocketDisconnect, RuntimeError):
                            page.result()
                        break
                    if self._conv_task in done and self._conv_task.cancelled():
                        continue                              # renewed: a new reader took over
                    for t in done:
                        if not t.cancelled() and t.exception():
                            log.warning("voice session ended: %r", t.exception())
                    await self.emit("error", code="engine_failed", detail="The speech model stopped. Start voice mode again.")
                    break
                if self.reply is not None:                    # you left mid-reply: keep what was said
                    with contextlib.suppress(Exception):
                        await asyncio.wait_for(self.finish_turn(interrupted=not self.reply.done.is_set(), played_ms=1e12), 8)
                await self.emit("done")
        except GpuCancelled:
            await self.fail(4409, "gpu_cancelled", "The wait for the GPU was cancelled.")
        finally:
            self.engine.sessions -= 1
            self.engine.touch()
            for t in [*tasks, getattr(self, "_conv_task", None)]:
                if t is not None:
                    t.cancel()
            for sock in (self.conv, self.asr):
                if sock is not None:
                    with contextlib.suppress(Exception):
                        await sock.close()
            if not self.closed:
                self.closed = True
                with contextlib.suppress(Exception):
                    await self.ws.close()


def mount(app: FastAPI) -> None:
    @app.websocket("/v1/realtime")
    async def realtime(ws: WebSocket) -> None:
        await Session(ws, app).run()
