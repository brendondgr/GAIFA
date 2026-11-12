"""A chat answer as words to say: markdown taken out (as web/chat/chat-speak.js does for reading aloud), in pieces."""

from __future__ import annotations

import re
from typing import Any, AsyncIterator

import httpx

from .numbers import spoken_numbers

MAX_CHARS = 4000                # of one answer; the rest is in the chat
CHUNK_CHARS = 400               # one request to the model's /tts
TTS_FRAMES = 2000               # /tts stops at 512 audio frames unless told


class SpeechFailed(Exception):
    code = "speech_failed"

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


async def tts_stream(port: int, text: str, voice: str = "female", language: str | None = None) -> AsyncIterator[tuple[str, bytes]]:
    """Say `text` with llama.cpp's /tts, a piece at a time: ("text", the piece as utf-8) before each piece's
    audio, then ("audio", PCM16 mono 24 kHz) as it is made."""
    req: dict[str, Any] = {"voice": voice, "response_format": "pcm16", "stream": True, "n_predict": TTS_FRAMES}
    if language:
        req["lang"] = language.split("-")[0]
    english = not language or language.lower().startswith("en")
    async with httpx.AsyncClient(timeout=httpx.Timeout(10, read=60)) as c:
        for part in chunks(text):
            yield "text", part.encode()
            words = spoken_numbers(part) if english else part        # the text on screen keeps its digits
            async with c.stream("POST", f"http://127.0.0.1:{port}/tts", json={**req, "input": words}) as r:
                if r.status_code >= 400:
                    raise SpeechFailed(f"The speech model answered HTTP {r.status_code} when asked to speak.")
                async for pcm in r.aiter_bytes():
                    yield "audio", pcm

_FENCE = re.compile(r"^(\s*)(`{3,}|~{3,})[^\n]*\n.*?\n\s*\2\s*$", re.M | re.S)
_SENTENCE = re.compile(r"(?<=[.!?…:;])\s+|\n+")


def speakable(md: str | None) -> str:
    s = re.sub(r"^\s*<think>.*?</think>\s*", "", str(md or ""), flags=re.I | re.S)
    s = _FENCE.sub("\n(a code block)\n", s)
    s = re.sub(r"<[^>\n]{1,200}>", "", s)                                   # tags
    s = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", s)                         # a picture: its caption
    s = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", s)                          # a link: its words
    s = re.sub(r"`([^`\n]+)`", r"\1", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"\1", s)
    s = re.sub(r"(^|[^*])\*([^*\n]+)\*", r"\1\2", s)
    s = re.sub(r"^#{1,6}\s+", "", s, flags=re.M)
    s = re.sub(r"^\s*[-*+]\s+", "", s, flags=re.M)
    s = re.sub(r"^\s*\|.*\|\s*$", "", s, flags=re.M)                        # tables aren't read
    s = re.sub(r"^\s*>\s?", "", s, flags=re.M)
    s = re.sub(r"https?://\S+", "", s)
    s = re.sub(r"\s*[—–]\s*", ", ", s).replace("→", " to ").replace("&", " and ")     # signs a voice stumbles on
    s = re.sub(r"~\s*(?=\d)", "about ", s)
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s).strip()
    if len(s) > MAX_CHARS:
        cut = s.rfind(".", 0, MAX_CHARS - 1) + 1
        s = s[:cut or MAX_CHARS]
    return s


def chunks(text: str, size: int = CHUNK_CHARS) -> list[str]:
    """Whole sentences, up to `size` characters each; a longer sentence is cut at a space."""
    out: list[str] = []
    cur = ""
    for sentence in (p.strip() for p in _SENTENCE.split(text)):
        while len(sentence) > size:
            cut = sentence.rfind(" ", 0, size)
            cut = cut if cut > size // 2 else size
            if cur:
                out.append(cur)
                cur = ""
            out.append(sentence[:cut].strip())
            sentence = sentence[cut:].strip()
        if not sentence:
            continue
        if cur and len(cur) + 1 + len(sentence) > size:
            out.append(cur)
            cur = sentence
        else:
            cur = f"{cur} {sentence}".strip()
    if cur:
        out.append(cur)
    return out
