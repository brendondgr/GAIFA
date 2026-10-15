"""vLLM's Prometheus /metrics → the numbers the status route shows (plan 18.5): requests running and
waiting, KV cache use, and tokens per second from the generation-token counter, sampled every 2 s
while the engine is ready."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections import deque
from typing import Any

import httpx

log = logging.getLogger("vllm")
LINE = re.compile(r"^([a-zA-Z_:][a-zA-Z0-9_:]*)(\{[^}]*\})?\s+(\S+)")


def parse(text: str) -> dict[str, float]:
    """Sum each metric over its label sets (one model per engine, so that's the total)."""
    out: dict[str, float] = {}
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        m = LINE.match(line)
        if not m:
            continue
        try:
            v = float(m.group(3))
        except ValueError:
            continue
        out[m.group(1)] = out.get(m.group(1), 0.0) + v
    return out


def summary(text: str) -> dict[str, float | None]:
    m = parse(text)

    def first(*names: str) -> float | None:
        return next((m[n] for n in names if n in m), None)

    return {
        "running": first("vllm:num_requests_running"),
        "waiting": first("vllm:num_requests_waiting"),
        "kv_cache": first("vllm:kv_cache_usage_perc", "vllm:gpu_cache_usage_perc"),   # 0–1
        "generation_tokens": first("vllm:generation_tokens_total"),
        "prompt_tokens": first("vllm:prompt_tokens_total"),
        "requests": first("vllm:request_success_total"),
    }


class Sampler:
    """Reads /metrics every `every` seconds while asked to; keeps the latest summary, the generation
    rate over the last window, and when the engine last did anything (for idle_s)."""

    def __init__(self, http: httpx.AsyncClient, every: float = 2.0, window: float = 10.0):
        self.http = http
        self.every = every
        self.window = window
        self.latest: dict[str, float | None] = {}
        self.samples: deque[tuple[float, float]] = deque()
        self.last_active = time.time()
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        if self._task is None or self._task.done():
            self.reset()
            self._task = asyncio.create_task(self._loop())

    def stop(self) -> None:
        if self._task:
            self._task.cancel()
            self._task = None
        self.reset()

    def reset(self) -> None:
        self.latest, self.samples = {}, deque()
        self.last_active = time.time()

    async def _loop(self) -> None:
        while True:
            await self.sample()
            await asyncio.sleep(self.every)

    async def sample(self) -> None:
        try:
            r = await self.http.get("/metrics")
            if r.status_code != 200:
                return
        except httpx.HTTPError:
            return
        self.add(summary(r.text), time.time())

    def add(self, s: dict[str, float | None], now: float) -> None:
        gen = s.get("generation_tokens")
        if gen is not None:
            if self.samples and gen != self.samples[-1][1]:
                self.last_active = now
            self.samples.append((now, gen))
            while len(self.samples) > 2 and now - self.samples[0][0] > self.window:
                self.samples.popleft()
        if (s.get("running") or 0) > 0 or (s.get("waiting") or 0) > 0:
            self.last_active = now
        self.latest = s

    @property
    def tokens_per_s(self) -> float:
        if len(self.samples) < 2:
            return 0.0
        (t0, g0), (t1, g1) = self.samples[0], self.samples[-1]
        return max(0.0, (g1 - g0) / (t1 - t0)) if t1 > t0 else 0.0

    @property
    def busy(self) -> bool:
        return (self.latest.get("running") or 0) > 0

    def view(self) -> dict[str, Any]:
        return {**self.latest, "tokens_per_s": round(self.tokens_per_s, 1), "idle_s": round(time.time() - self.last_active, 1)}
