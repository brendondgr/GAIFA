"""Voice mode through the chat's agent (plan voice-speech-model 6.2; `[voice_mode] answers = "agent"`).

The speech model only hears and speaks here. Your turn is written down by the transcription session and sent to
the chat as a message of yours (the agent's /voice-ask), so the chat's own model answers it the way it answers a
typed one: its harness, tools, apps, memory, modes and cards. Each step's text is spoken as it comes
(/voice-answer?step=1 → llama.cpp's /tts, streamed). Talking over it stops the speech, and the turn too when it is
still running. The GPU slot is held only while you are heard and while it speaks, so the chat's model and the
apps its tools start get the GPU in between.

Plan voice-mute 3.3: an interruption first only pauses. The chat's turn keeps running while what interrupted is
heard; when it turns out to hold no words (a cough, a door, a word of filler), the answer goes on from the start of
the sentence it stopped in. With words, the chat's turn is stopped and what you said is the next message, as before.
A press of push to talk is always a real interruption.
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
#: what a false interruption's transcription may hold and still give the answer back
FILLER = {"", "um", "uh", "uhm", "hm", "hmm", "mm", "mhm", "ah", "oh", "eh", "you", "the", "a", "huh", "thank you", "thanks", "mm hm", "uh huh", "okay"}


MS_PER_CHAR = 70                   # about how long the speech model takes to say a character, for a chunk still coming


def heard_upto(marks: list[tuple[int, int, int]], audio_bytes: int, played: int, bytes_per_ms: float, done: bool = False) -> int:
    """How far into a step's text you heard: `marks` are its spoken chunks (char start, length, audio start),
    `audio_bytes` how much of its audio was sent, `played` how much of that played (both from the step's start);
    `done`: all of it was made (else the last chunk's length is guessed from its text)."""
    pos = 0
    for i, (start, n, at) in enumerate(marks):
        if played < at:
            break
        end = marks[i + 1][2] if i + 1 < len(marks) else audio_bytes if done else max(audio_bytes, at + n * MS_PER_CHAR * bytes_per_ms)
        pos = start + int(n * min(1.0, (played - at) / max(1.0, end - at)))
    return pos


def resume_point(text: str, upto: int) -> int:
    """Where in `text` (whitespace as single spaces) to go on: the start of the sentence `upto` is in."""
    start = max(text.rfind(p, 0, upto) for p in (". ", "! ", "? ", "\n"))
    return 0 if upto <= 0 or start < 0 else start + 2


#: one word that is meant: it stops or steers the answer, so it is never taken for noise
COMMANDS = {"stop", "wait", "no", "nope", "yes", "yeah", "yep", "pause", "cancel", "enough", "quiet", "shush", "hush", "hold",
            "next", "skip", "what", "why", "how", "where", "when", "who", "which", "repeat", "again", "louder", "slower", "sorry"}


def is_filler(words: str) -> bool:
    """What interrupted held no words meant for it: nothing, filler, or one word that isn't a command (a cough or a
    murmur the transcription made a word of, "Mm-hm" written as "Mem")."""
    w = " ".join("".join(c if c.isalnum() else " " if c in " -" else "" for c in words.lower()).split())
    return w in FILLER or (" " not in w and w not in COMMANDS)


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
        self.after = 0                     # the chat's seq the answer has been read up to
        self.step = ""                     # the step being spoken, its text as spoken (single spaces)
        self.step_said = 0                 # len(self.said) and self.audio_bytes when that step began
        self.step_audio = 0
        self.marks: list[tuple[int, int, int]] = []   # the step's chunks: (char start, length, audio start), audio from the step's start
        self.step_done = False             # all of the step's speech was made
        self.player_from = 0               # self.audio_bytes where the page's player started (a resume starts a new one)
        self.paused: dict[str, Any] | None = None     # an interruption not yet known to be one (3.3)

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
        if self.paused is None:
            self.user, self.said, self.audio_bytes, self.first_audio_ms, self.player_from = "", [], 0, None, 0
        self.task = asyncio.create_task(self.turn())

    async def turn(self) -> None:
        s = self.s
        try:
            try:
                heard = (await asyncio.wait_for(asyncio.shield(s.heard), HEARD_WAIT_S)).strip()
            except TimeoutError:
                heard = ""
            finally:
                await s.gpu.off()
            if self.paused is not None:
                p, self.paused = self.paused, None
                if is_filler(heard):                   # noise: the answer goes on where it stopped
                    self.player_from = self.audio_bytes
                    await s.emit("resumed")
                    return await self.steps(p["after"], first=p["rest"])
                if p["running"]:                       # words: that turn ends here, and this is the next one
                    self.running = False
                    with contextlib.suppress(HubError):
                        await s.hub.voice_stop(s.start.thread)
                await self.report(True)
                self.said, self.audio_bytes, self.first_audio_ms, self.player_from = [], 0, None, 0
            self.user = heard
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
            await self.steps(sent["seq"])
        except asyncio.CancelledError:
            raise
        except (HubError, SpeechFailed, httpx.HTTPError, GpuCancelled, OSError) as e:
            log.warning("a voice turn through the chat failed: %r", e)
            await s.emit("error", code=getattr(e, "code", "speech_failed"), detail=getattr(e, "detail", None) or f"The answer couldn't be spoken ({e}); it is in the chat.")
            await self.finish(False)

    async def steps(self, after: int, first: str = "") -> None:
        """Speak the chat's turn from `after` (and `first`, the rest of a step that was paused) to its end."""
        s = self.s
        self.after = after
        try:
            if first:
                await self.speak_step(first)
            while self.running:                        # a paused turn that had ended has nothing more to read
                ans = await s.hub.voice_step(s.start.thread, self.after)
                self.after = ans.get("seq", self.after)
                if text := speakable(ans.get("text")):
                    await self.speak_step(text)
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

    async def speak_step(self, text: str) -> None:
        self.step, self.step_said, self.step_audio, self.marks = " ".join(text.split()), len(self.said), self.audio_bytes, []
        self.step_done = False
        await self.say(self.step)
        self.step_done = True

    async def say(self, text: str) -> None:
        """Speak one step's text with the model's /tts, streamed to the page as it is made."""
        s = self.s
        await s.gpu.on()
        try:
            async for kind, data in tts_stream(self.port, text, s.start.voice, s.start.language):
                if kind == "text":
                    chunk = data.decode()
                    at = sum(n + 1 for _, n, _ in self.marks)
                    self.marks.append((at, len(chunk), self.audio_bytes - self.step_audio))
                    self.said.append(chunk)
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

    async def report(self, interrupted: bool) -> None:
        """Tell the page the turn is over (the chat already holds it)."""
        s = self.s
        said = " ".join(self.said)
        if self.user:
            s.turns += [{"role": "user", "text": self.user}, *([{"role": "assistant", "text": said}] if said else [])]
            s.stats.turn(None)
        await s.emit("turn", user=self.user, assistant=said, first_audio_ms=self.first_audio_ms, interrupted=interrupted,
                     saved=bool(self.user), answers="agent")

    async def finish(self, interrupted: bool) -> None:
        """The turn is over for you: report it and listen again."""
        s = self.s
        s.hold.clear()
        s.hold_bytes = 0
        await self.report(interrupted)
        s.detector.reset()
        await s.set_mode("listening")

    async def interrupt(self, played_ms: float = 0.0, pressed: bool = False) -> None:
        """You talked over it: stop speaking and hear what you say. A press of push to talk stops the chat's turn
        at once; otherwise it is paused until what interrupted is known to hold words (3.3)."""
        s = self.s
        task, self.task = self.task, None
        if task is None or task.done() or s.mode not in ("thinking", "speaking"):
            return
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await s.gpu.off()
        held = b"".join(s.hold)
        if not pressed and self.user and self.step:
            rate = s.out_rate * 2 / 1000                                   # bytes per ms
            played = int(self.player_from + played_ms * rate) - self.step_audio
            cut = resume_point(self.step, heard_upto(self.marks, self.audio_bytes - self.step_audio, played, rate, self.step_done))
            self.said = [*self.said[:self.step_said], *([self.step[:cut].strip()] if cut else [])]
            self.audio_bytes = self.step_audio
            self.paused = {"rest": self.step[cut:], "after": self.after, "running": self.running}
            s.hold.clear()
            s.hold_bytes = 0
            s.detector.reset()
            await s.set_mode("listening")
            return await s.on_detected(s.detector.begin(held))
        if self.running:
            self.running = False
            with contextlib.suppress(HubError):
                await s.hub.voice_stop(s.start.thread)
        await self.finish(True)
        await s.on_detected(s.detector.begin(held))

    async def close(self) -> None:
        task, self.task = self.task, None
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
