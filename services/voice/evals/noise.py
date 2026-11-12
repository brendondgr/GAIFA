"""Plan voice-mute 3.1: which rule tells talking over a reply from noise in the room.

Each clip is put 0.5 s into 3 s of a quiet room and fed, as the page and the mod would see it, to:

- `level`: the page's rule today (chat-voice.js `bargeTracker`: the 100 ms level of `levelOf` over 0.5 for 350 ms,
  dips under 250 ms forgiven);
- `vad p/ms`: Silero's speech probability (the mod's turn detector's model) at or over `p` for `ms`, dips under
  `gap` ms forgiven;
- `level+vad`: both.

Noise is synthesized (white and pink noise, a fan, keyboard clicks, a door, a cough, a clap, music) at two levels;
a TV is the speech model's own voice, quiet and loud; interruptions are that voice saying short things at a normal
level. Speech clips come from the voice mod's `/v1/speech` (`--url`), kept in `evals/noise/` so a rerun needs no GPU.

    .venv/bin/python -m evals.noise [--url http://127.0.0.1:7000/api/s/voice] [--json out.json]

Prints a table of false interruptions (noise that would stop the reply) and missed ones (speech that wouldn't), with
the median time to decide.
"""

from __future__ import annotations

import argparse
import io
import json
import statistics
import wave
from pathlib import Path

import numpy as np

from voice import vad

RATE = 16000
HERE = Path(__file__).resolve().parent / "noise"
MODEL = Path(__file__).resolve().parents[1] / "runtime" / "vad" / "silero_vad.onnx"
SAYINGS = {"wait": "Wait, wait.", "stop": "Stop.", "hold-on": "Hold on a second.", "no": "No, that's not what I meant.",
           "actually": "Actually, can you check my calendar instead?", "okay": "Okay, okay, I get it.",
           "question": "What time is it?", "thanks": "Thanks, that's enough."}
TV = "And now the weather for the weekend. Expect clouds in the morning, clearing by the afternoon, with highs near sixty."


def db(x: np.ndarray, target_dbfs: float) -> np.ndarray:
    rms = float(np.sqrt(np.mean(x ** 2))) or 1e-9
    return x * (10 ** (target_dbfs / 20) / rms)


def read_wav(data: bytes) -> np.ndarray:
    with wave.open(io.BytesIO(data)) as w:
        x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
        rate = w.getframerate()
    return np.interp(np.arange(int(len(x) * RATE / rate)) * rate / RATE, np.arange(len(x)), x).astype(np.float32)


def write_wav(path: Path, x: np.ndarray) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(RATE)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes())


def speech(url: str | None) -> dict[str, np.ndarray]:
    """The spoken clips, from evals/noise/ or made by the voice mod."""
    HERE.mkdir(exist_ok=True)
    out: dict[str, np.ndarray] = {}
    for name, text in {**SAYINGS, "tv": TV}.items():
        path = HERE / f"{name}.wav"
        if not path.is_file():
            if not url:
                raise SystemExit(f"{path} is missing: pass --url to make it with the voice mod")
            import httpx

            r = httpx.post(f"{url.rstrip('/')}/v1/speech", json={"text": text, "voice": "male"}, timeout=120)
            r.raise_for_status()
            write_wav(path, read_wav(r.content))
        with path.open("rb") as f:
            out[name] = read_wav(f.read())
    return out


def synth(rng: np.random.Generator) -> dict[str, np.ndarray]:
    """Room noise, made here: each about a second or two."""
    t = lambda s: np.arange(int(s * RATE)) / RATE                                   # noqa: E731
    white = rng.normal(0, 1, int(1.5 * RATE)).astype(np.float32)
    pink = np.cumsum(rng.normal(0, 1, int(1.5 * RATE))).astype(np.float32)
    pink -= np.convolve(pink, np.ones(400) / 400, mode="same")
    fan = (np.sin(2 * np.pi * 120 * t(2)) + 0.3 * rng.normal(0, 1, int(2 * RATE))).astype(np.float32)
    keys = np.zeros(int(2 * RATE), np.float32)
    for at in rng.uniform(0, 1.9, 14):
        i = int(at * RATE)
        keys[i:i + 160] += rng.normal(0, 1, 160) * np.exp(-np.arange(160) / 25)
    door = np.zeros(int(1.2 * RATE), np.float32)
    door[:4000] = rng.normal(0, 1, 4000) * np.exp(-np.arange(4000) / 700) + np.sin(2 * np.pi * 60 * t(0.25)[:4000]) * np.exp(-np.arange(4000) / 1500)
    cough = np.zeros(int(1.2 * RATE), np.float32)
    for start in (0.0, 0.45):
        n = int(0.28 * RATE)
        burst = rng.normal(0, 1, n) * np.exp(-np.arange(n) / (0.08 * RATE))
        burst = np.convolve(burst, np.hanning(9) / 4, mode="same")
        cough[int(start * RATE):int(start * RATE) + n] += burst
    clap = np.zeros(int(1.5 * RATE), np.float32)
    for k in range(5):
        i = int(k * 0.28 * RATE)
        clap[i:i + 800] += rng.normal(0, 1, 800) * np.exp(-np.arange(800) / 120)
    tt = t(2)
    chord = sum(np.sin(2 * np.pi * f * tt) for f in (220, 277.2, 329.6, 440)) * (0.5 + 0.5 * (np.sin(2 * np.pi * 2 * tt) > 0))
    music = (chord + 0.4 * np.sin(2 * np.pi * 110 * tt) * (np.sin(2 * np.pi * 4 * tt) > 0.6)).astype(np.float32)
    return {"white": white, "pink": pink, "fan": fan, "keyboard": keys, "door": door, "cough": cough, "clap": clap, "music": music}


def cases(rng: np.random.Generator, spoken: dict[str, np.ndarray]) -> list[tuple[str, str, np.ndarray]]:
    """(name, kind: noise | speech, 3 s of input with the clip at 0.5 s)."""
    out = []
    room = lambda: (rng.normal(0, 1, 3 * RATE) * 10 ** (-62 / 20)).astype(np.float32)   # noqa: E731
    def place(x: np.ndarray) -> np.ndarray:
        y = room()
        n = min(len(x), len(y) - RATE // 2)
        y[RATE // 2:RATE // 2 + n] += x[:n]
        return y
    for name, x in synth(rng).items():
        for level in (-35, -20):
            out.append((f"{name} {level} dB", "noise", place(db(x, level))))
    for level in (-38, -26):
        out.append((f"tv {level} dB", "noise", place(db(spoken["tv"][:int(2.4 * RATE)], level))))
    for name in SAYINGS:
        out.append((f"“{SAYINGS[name]}”", "speech", place(db(spoken[name], -24))))
        out.append((f"“{SAYINGS[name]}” quiet", "speech", place(db(spoken[name], -34))))
    return out


class LevelRule:
    """The page's barge-in today: 100 ms levels."""

    def __init__(self, level=0.5, ms=350, gap=250) -> None:
        self.level, self.ms, self.gap = level, ms, gap

    def first(self, x: np.ndarray) -> float | None:
        since, last = None, -1e9
        for k in range(len(x) // 1600):
            f = x[k * 1600:(k + 1) * 1600]
            rms = float(np.sqrt(np.mean(f ** 2)))
            lv = 0 if rms <= 0.001 else min(1, max(0, 1 + np.log10(rms) / 3))
            now = (k + 1) * 100
            if lv < self.level:
                continue
            if since is None or now - last > self.gap:
                since = now
            last = now
            if now - since >= self.ms:
                return now
        return None


class VadRule:
    def __init__(self, model, p=0.6, ms=300, gap=100, level: LevelRule | None = None) -> None:
        self.model, self.p, self.ms, self.gap, self.level = model, p, ms, gap, level

    def first(self, x: np.ndarray) -> float | None:
        b = vad.BargeDetector(self.model, rate=RATE, ms=self.ms, prob=self.p, gap_ms=self.gap)
        lv_at = self.level.first(x) if self.level else 0
        if lv_at is None:
            return None
        pcm = (np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes()
        for k in range(0, len(pcm), 3200):
            if b.feed(pcm[k:k + 3200]):
                return max((k + 3200) / 32, lv_at)
        return None


def run(url: str | None) -> dict:
    rng = np.random.default_rng(7)
    model = vad.make_vad(MODEL)
    if model.kind != "silero":
        raise SystemExit(f"Silero isn't there ({MODEL}): run install.sh")
    rules = {"level (today)": LevelRule()}
    for p in (0.5, 0.7, 0.85):
        for ms in (200, 300, 450):
            rules[f"vad {p}/{ms}"] = VadRule(model, p, ms)
    rules["level + vad 0.7/200"] = VadRule(model, 0.7, 200, level=LevelRule())
    all_cases = cases(rng, speech(url))
    out: dict = {"rules": {}, "cases": [c[0] for c in all_cases]}
    for name, rule in rules.items():
        res = [(c, kind, rule.first(x)) for c, kind, x in all_cases]
        false = [c for c, kind, t in res if kind == "noise" and t is not None]
        missed = [c for c, kind, t in res if kind == "speech" and t is None]
        took = [t - 500 for _, kind, t in res if kind == "speech" and t is not None]
        out["rules"][name] = {"false": false, "missed": missed, "median_ms": round(statistics.median(took)) if took else None}
    return out


def table(r: dict) -> str:
    n_noise = sum(1 for c in r["cases"] if not c.startswith("“"))
    n_speech = len(r["cases"]) - n_noise
    lines = [f"| Rule | False (of {n_noise} noises) | Missed (of {n_speech} sayings) | Median time to decide | Which |",
             "| --- | --- | --- | --- | --- |"]
    for name, v in r["rules"].items():
        which = "; ".join([*v["false"], *(f"missed {m}" for m in v["missed"])]) or "—"
        lines.append(f"| {name} | {len(v['false'])} | {len(v['missed'])} | {v['median_ms']} ms | {which} |")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--url", help="the voice mod (or the hub's /api/s/voice), to make the spoken clips")
    ap.add_argument("--json", type=Path)
    a = ap.parse_args()
    r = run(a.url)
    if a.json:
        a.json.write_text(json.dumps(r, indent=1))
    print(table(r))


if __name__ == "__main__":
    main()
