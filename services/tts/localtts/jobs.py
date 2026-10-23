"""Speech as a job (plan 45.4), so a speech can report its progress and be heard while it's made.

    POST /v1/speech/jobs {the body of POST /v1/speech}  → 202 {id, state}
    GET  /v1/speech/jobs/{id}                           → {id, state, label, progress, live?, outputs?, error?, seconds?}
    GET  /v1/speech/jobs/{id}/audio?offset=&wait=       → the PCM (s16le, mono) made after `offset` bytes; X-Done: 1 at the end
    POST /v1/speech/jobs/{id}/cancel

The engine yields PCM as it makes it; the job keeps it, so a reader can play from the first chunk. `live.lines`
([done, of]) is an estimate: the share of the text spoken so far, from the audio made against the length expected
at this voice's pace. When it ends, the clip is saved to Outputs as `POST /v1/speech` saves it, and the job's
`outputs` names it. Jobs are kept for an hour.
"""

from __future__ import annotations

import asyncio
import re
import time
import uuid
from typing import Any, Callable

SECONDS_PER_CHAR = 0.065        # a calm reading pace; the estimate only places the highlight
KEEP_S = 3600
CHUNK_MAX = 1 << 20


def lines_of(text: str) -> list[str]:
    """The text as the card shows it: its non-empty lines, long ones split at sentence ends."""
    out: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if len(line) <= 160:
            out.append(line)
        else:
            out.extend(s.strip() for s in re.split(r"(?<=[.!?])\s+", line) if s.strip())
    return out or [text.strip()]


def lines_done(text: str, audio_s: float, done: bool) -> list[int]:
    lines = lines_of(text)
    if done:
        return [len(lines), len(lines)]
    expected = max(0.5, len(text) * SECONDS_PER_CHAR)
    reached, at = audio_s / expected * len(text), 0
    for i, line in enumerate(lines):
        at += len(line) + 1
        if at > reached:
            return [i, len(lines)]
    return [len(lines) - 1, len(lines)]


class SpeechJobs:
    def __init__(self) -> None:
        self.jobs: dict[str, dict[str, Any]] = {}

    def _prune(self) -> None:
        now = time.time()
        for jid, j in list(self.jobs.items()):
            if j["state"] not in ("queued", "running") and now - (j.get("finished") or now) > KEEP_S:
                del self.jobs[jid]

    def start(self, text: str, voice: str, engine: Any, params: dict, finish: Callable[[bytes, dict, int], dict | None]) -> dict:
        """Run `engine.generate(**params)` as a job; `finish(pcm, stats, sample_rate)` saves the clip and returns its output."""
        self._prune()
        jid = "s_" + uuid.uuid4().hex[:10]
        j: dict[str, Any] = {"id": jid, "state": "queued", "label": f"Speech: {text[:60]}", "text": text, "voice": voice,
                             "pcm": bytearray(), "sr": engine.info.get("sample_rate", 24000), "created": time.time(),
                             "changed": asyncio.Event(), "outputs": [], "error": None}
        self.jobs[jid] = j

        async def run() -> None:
            stats: dict = {}
            gen = engine.generate(request_id=jid, **params)
            try:
                async for item in gen:
                    if isinstance(item, bytes):
                        if j["state"] == "queued":
                            j["state"], j["started"] = "running", time.time()
                        j["pcm"].extend(item)
                        self._bump(j)
                    else:
                        stats = item
                j["sr"] = engine.info.get("sample_rate", j["sr"])
                out = finish(bytes(j["pcm"]), stats, j["sr"])
                if out:
                    j["outputs"] = [out]
                j["state"] = "done"
            except asyncio.CancelledError:
                j["state"] = "cancelled"
            except Exception as e:  # noqa: BLE001 - the job reports it
                j["state"], j["error"] = "failed", str(e)[:400]
            finally:
                await gen.aclose()
                j["finished"] = time.time()
                self._bump(j)

        j["task"] = asyncio.create_task(run())
        return self.public(j)

    @staticmethod
    def _bump(j: dict) -> None:
        j["changed"].set()
        j["changed"] = asyncio.Event()

    def get(self, jid: str) -> dict | None:
        return self.jobs.get(jid)

    def audio_s(self, j: dict) -> float:
        return len(j["pcm"]) / 2 / (j["sr"] or 24000)

    def public(self, j: dict, waiting: dict | None = None) -> dict:
        done = j["state"] == "done"
        made = self.audio_s(j)
        out: dict[str, Any] = {"id": j["id"], "state": j["state"], "label": j["label"], "voice": j["voice"],
                               "audio_s": round(made, 2)}
        expected = max(0.5, len(j["text"]) * SECONDS_PER_CHAR)
        out["progress"] = 1.0 if done else round(min(0.95, made / expected), 3) if made else None
        if j["state"] in ("queued", "running"):
            live: dict[str, Any] = {"stage": "speaking" if made else "queued" if waiting else "loading",
                                    "lines": lines_done(j["text"], made, False),
                                    "audio": f"/v1/speech/jobs/{j['id']}/audio"}
            if j.get("started") and made > 0.5:
                rate = (time.time() - j["started"]) / made        # seconds of work per second of audio
                live["eta_s"] = round(max(0.0, (expected - made) * rate), 1)
            out["live"] = live
        if waiting:
            out.update(stage="waiting_gpu", ahead=waiting.get("ahead") or [], eta_s=waiting.get("eta_s"))
        if j["outputs"]:
            out["outputs"] = j["outputs"]
        if j["error"]:
            out["error"] = j["error"]
        if j.get("finished") and j.get("created"):
            out["seconds"] = round(j["finished"] - j["created"], 1)
        return out

    async def audio(self, j: dict, offset: int, wait: float) -> tuple[bytes, bool]:
        """PCM after `offset`, waiting up to `wait` s for some; (bytes, finished)."""
        deadline = time.monotonic() + wait
        while len(j["pcm"]) <= offset and j["state"] in ("queued", "running"):
            left = deadline - time.monotonic()
            if left <= 0:
                break
            try:
                await asyncio.wait_for(j["changed"].wait(), timeout=left)
            except asyncio.TimeoutError:
                break
        data = bytes(j["pcm"][offset:offset + CHUNK_MAX])
        finished = j["state"] not in ("queued", "running") and offset + len(data) >= len(j["pcm"])
        return data, finished

    async def cancel(self, j: dict) -> None:
        t = j.get("task")
        if t and not t.done():
            t.cancel()
            await asyncio.gather(t, return_exceptions=True)

JOBS = SpeechJobs()
