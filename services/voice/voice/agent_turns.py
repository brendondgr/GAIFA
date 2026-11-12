"""Voice mode through the chat's agent (plan voice-speech-model 6.2; `[voice_mode] answers = "agent"`).

The speech model only hears and speaks here. Your turn is written down by the transcription session and sent to
the chat as a message of yours (the agent's /voice-ask), so the chat's own model answers it the way it answers a
typed one: its harness, tools, apps, memory, modes and cards. Each step's text is spoken as it comes
(/voice-answer?step=1 → llama.cpp's /tts, streamed). Talking over it stops the speech, and the turn too when it is
still running. The GPU slot is held only while you are heard and while it speaks, so the chat's model and the
apps its tools start get the GPU in between.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from typing import Any, Awaitable, Callable

import httpx

from .gpu_slot import GpuCancelled, gpu_slot
from .hub import HubError
from .speak import SpeechFailed, speakable, tts_stream

log = logging.getLogger(__name__)

HEARD_WAIT_S = 15.0


class Gpu:
    """The GPU slot, taken and given back as the conversation needs it."""

    def __init__(self, label: str, on_wait: Callable[[Any], Awaitable[None]] | None = None) -> None:
        self.label, self.on_wait = label, on_wait
        self.cm: Any = None
        self.lock = asyncio.Lock()

    async def on(self) -> None:
        async with self.lock:
            if self.cm is None:
                cm = gpu_slot(self.label, est_s=120, on_wait=self.on_wait)
                await cm.__aenter__()
                self.cm = cm

    async def off(self) -> None:
        async with self.lock:
            cm, self.cm = self.cm, None
            if cm is not None:
                with contextlib.suppress(Exception):
                    await cm.__aexit__(None, None, None)


class AgentTurns:
    def __init__(self, session: Any, port: int) -> None:
        self.s, self.port = session, port
        self.task: asyncio.Task | None = None
        self.played = asyncio.Event()
        self.running = False               # the chat's turn this conversation started is still going
        self.user = ""
        self.said: list[str] = []
        self.audio_bytes = 0
        self.first_audio_ms: int | None = None

    async def hearing(self) -> None:
        await self.s.gpu.on()

    async def end_turn(self, typed: str | None) -> None:
        """Your turn is over: write it down, hand it to the chat."""
        s = self.s
        s.t_end = time.monotonic()
        s.heard = asyncio.get_running_loop().create_future()
        if typed is None:
            await s.up(s.asr, {"type": "input_audio_buffer.commit"})
        else:
            s.heard.set_result(typed)
            await s.emit("heard", text=typed)
        await s.set_mode("thinking")
        self.played = asyncio.Event()
        self.user, self.said, self.audio_bytes, self.first_audio_ms = "", [], 0, None
        self.task = asyncio.create_task(self.turn())

    async def turn(self) -> None:
        s = self.s
        try:
            try:
                self.user = (await asyncio.wait_for(asyncio.shield(s.heard), HEARD_WAIT_S)).strip()
            except TimeoutError:
                self.user = ""
            finally:
                await s.gpu.off()
            if not self.user:
                return await self.finish(False)
            try:
                sent = await s.hub.voice_ask(s.start.thread, self.user)
            except HubError as e:
                busy = e.status == 409
                await s.emit("error", code="turn_running" if busy else e.code,
                             detail="The chat is busy with another turn; say it again when it has finished." if busy else e.detail)
                self.user = ""
                return await self.finish(False)
            self.running = True
            after = sent["seq"]
            while True:
                ans = await s.hub.voice_step(s.start.thread, after)
                after = ans.get("seq", after)
                if text := speakable(ans.get("text")):
                    await self.say(text)
                if ans.get("state") == "done":
                    break
            self.running = False
            await s.emit("said", text=" ".join(self.said), final=True, audio_ms=round(self.audio_bytes / 2 / s.out_rate * 1000))
            if self.audio_bytes:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self.played.wait(), self.audio_bytes / 2 / s.out_rate + 15)
            await self.finish(False)
        except asyncio.CancelledError:
            raise
        except (HubError, SpeechFailed, httpx.HTTPError, GpuCancelled, OSError) as e:
            log.warning("a voice turn through the chat failed: %r", e)
            await s.emit("error", code=getattr(e, "code", "speech_failed"), detail=getattr(e, "detail", None) or f"The answer couldn't be spoken ({e}); it is in the chat.")
            await self.finish(False)

    async def say(self, text: str) -> None:
        """Speak one step's text with the model's /tts, streamed to the page as it is made."""
        s = self.s
        await s.gpu.on()
        try:
            async for kind, data in tts_stream(self.port, text, s.start.voice, s.start.language):
                if kind == "text":
                    self.said.append(data.decode())
                    await s.emit("said", text=" ".join(self.said), final=False)
                    s.engine.touch()
                    continue
                if self.first_audio_ms is None:
                    self.first_audio_ms = round((time.monotonic() - s.t_end) * 1000)
                await s.set_mode("speaking")
                self.audio_bytes += len(data)
                await s.audio_out(data)
        finally:
            await s.gpu.off()

    async def finish(self, interrupted: bool) -> None:
        """The turn is over for you: report it (the chat already holds it) and listen again."""
        s = self.s
        s.hold.clear()
        s.hold_bytes = 0
        said = " ".join(self.said)
        if self.user:
            s.turns += [{"role": "user", "text": self.user}, *([{"role": "assistant", "text": said}] if said else [])]
            s.stats.turn(None)
        await s.emit("turn", user=self.user, assistant=said, first_audio_ms=self.first_audio_ms, interrupted=interrupted,
                     saved=bool(self.user), answers="agent")
        s.detector.reset()
        await s.set_mode("listening")

    async def interrupt(self) -> None:
        """You talked over it: stop speaking, stop the chat's turn if it still runs, and hear what you say."""
        s = self.s
        task, self.task = self.task, None
        if task is None or task.done() or s.mode not in ("thinking", "speaking"):
            return
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await s.gpu.off()
        if self.running:
            self.running = False
            with contextlib.suppress(HubError):
                await s.hub.voice_stop(s.start.thread)
        held = b"".join(s.hold)
        await self.finish(True)
        await s.on_detected(s.detector.begin(held))

    async def close(self) -> None:
        task, self.task = self.task, None
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
