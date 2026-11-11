"""A client for the mod's /v1/realtime, for the comparison and for checks by hand.

    .venv/bin/python -m evals.client --url ws://127.0.0.1:5110/v1/realtime question.wav --text "And Spain?"

Each WAV (PCM16 mono) is one spoken turn, sent in real time and followed by quiet so the mod finds the pause;
each --text is a typed turn. Prints every turn and saves the replies as WAVs with --out.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
import wave
from pathlib import Path
from typing import Any

import websockets


def read_wav(path: str | Path) -> tuple[bytes, int]:
    with wave.open(str(path), "rb") as f:
        assert f.getsampwidth() == 2 and f.getnchannels() == 1, "PCM16 mono WAV files only"
        return f.readframes(f.getnframes()), f.getframerate()


def write_wav(path: str | Path, pcm: bytes, rate: int) -> None:
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(rate)
        f.writeframes(pcm)


class Talk:
    """One conversation. `turn()` sends a spoken or typed turn and returns what came back."""

    def __init__(self, url: str, **start: Any) -> None:
        self.url, self.start = url, {"type": "start", **start}
        self.ws = None
        self.ready: dict[str, Any] = {}

    async def __aenter__(self) -> Talk:
        self.ws = await websockets.connect(self.url, max_size=None)
        await self.ws.send(json.dumps(self.start))
        while True:
            ev = json.loads(await self.ws.recv())
            if ev["type"] == "error":
                raise RuntimeError(f"{ev['code']}: {ev['detail']}")
            if ev["type"] == "ready":
                self.ready = ev
            if ev["type"] == "listening":
                return self

    async def __aexit__(self, *exc: Any) -> None:
        with_stop = self.ws is not None
        if with_stop:
            try:
                await self.ws.send(json.dumps({"type": "stop"}))
                await self.ws.close()
            except websockets.WebSocketException:
                pass

    async def _speak(self, pcm: bytes, rate: int, pause_s: float) -> float:
        step = rate // 10 * 2
        data = pcm + b"\x00\x00" * int(rate * pause_s)
        end = time.monotonic()
        for i in range(0, len(data), step):
            await self.ws.send(data[i:i + step])
            if i < len(pcm):
                end = time.monotonic() + 0.1
            await asyncio.sleep(0.1)
        return end

    async def turn(self, wav: str | Path | None = None, text: str | None = None, interrupt_after_s: float | None = None,
                   timeout: float = 90) -> dict[str, Any]:
        """Send one turn; the reply's audio is "played" at once unless interrupt_after_s cuts it."""
        rate = self.start.get("sample_rate", 16000)
        sender = None
        t_sent = time.monotonic()
        if wav is not None:
            pcm, wav_rate = read_wav(wav)
            assert wav_rate == rate, f"{wav} is {wav_rate} Hz; start the talk with sample_rate={wav_rate}"
            sender = asyncio.create_task(self._speak(pcm, rate, 3.0))
        else:
            await self.ws.send(json.dumps({"type": "text", "text": text}))
        audio = bytearray()
        out: dict[str, Any] = {"events": [], "errors": []}
        t_think = None
        interrupted = False
        async with asyncio.timeout(timeout):
            while True:
                msg = await self.ws.recv()
                if isinstance(msg, bytes):
                    audio += msg
                    if "first_audio_s" not in out:
                        out["first_audio_s"] = round(time.monotonic() - (t_think or t_sent), 3)
                    if interrupt_after_s is not None and not interrupted and \
                            len(audio) / 2 / self.ready["sample_rate_out"] >= interrupt_after_s:
                        interrupted = True
                        await self.ws.send(json.dumps({"type": "interrupt", "played_ms": interrupt_after_s * 1000}))
                    continue
                ev = json.loads(msg)
                out["events"].append(ev["type"])
                if ev["type"] == "thinking":
                    t_think = time.monotonic()
                elif ev["type"] == "heard":
                    out["heard"] = ev["text"]
                elif ev["type"] == "said" and ev["final"]:
                    out["said"], out["audio_ms"] = ev["text"], ev.get("audio_ms")
                    out["reply_s"] = round(time.monotonic() - (t_think or t_sent), 3)
                    if not interrupted:
                        await self.ws.send(json.dumps({"type": "played"}))
                elif ev["type"] == "tool":
                    out.setdefault("tools", []).append(ev)
                elif ev["type"] == "error":
                    out["errors"].append(ev)
                elif ev["type"] == "turn":
                    out["turn"] = ev
                    break
        if sender is not None:
            sender.cancel()
        out["audio"] = bytes(audio)
        return out


async def main(args: argparse.Namespace) -> None:
    start = {"voice": args.voice, "pause_ms": args.pause_ms, "sample_rate": args.rate}
    if args.thread:
        start["thread"] = args.thread
    if args.language:
        start["language"] = args.language
    async with Talk(args.url, **start) as talk:
        print("ready:", talk.ready)
        turns = [("wav", w) for w in args.wav] + [("text", t) for t in args.text]
        for i, (kind, src) in enumerate(turns):
            r = await talk.turn(**{kind: src}, interrupt_after_s=args.interrupt)
            t = r["turn"]
            print(f"--- {i} ({kind}: {src})\n  you: {t['user']!r}\n  it:  {t['assistant']!r}\n  first audio {t['first_audio_ms']} ms after "
                  f"the pause; {r.get('audio_ms')} ms of speech in {r.get('reply_s')} s; interrupted={t['interrupted']} saved={t['saved']}"
                  + (f"\n  errors: {r['errors']}" if r["errors"] else ""))
            if args.out and r["audio"]:
                write_wav(Path(args.out) / f"reply-{i}.wav", r["audio"], talk.ready["sample_rate_out"])


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("wav", nargs="*")
    p.add_argument("--text", action="append", default=[])
    p.add_argument("--url", default="ws://127.0.0.1:5110/v1/realtime")
    p.add_argument("--thread")
    p.add_argument("--voice", default="female")
    p.add_argument("--language")
    p.add_argument("--pause-ms", type=int, default=800)
    p.add_argument("--rate", type=int, default=16000)
    p.add_argument("--interrupt", type=float, help="interrupt each reply after this many seconds of it")
    p.add_argument("--out", help="a folder for the replies' WAVs")
    asyncio.run(main(p.parse_args()))
