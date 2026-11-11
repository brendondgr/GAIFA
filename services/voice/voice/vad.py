"""Finding the end of your turn: voice activity on 32 ms frames, then a pause.

llama.cpp's realtime server has no turn detection (docs/voice-spike.md), so the bridge runs this on the
microphone audio. `SileroVad` is the Silero model on the CPU (runtime/vad/silero_vad.onnx, fetched by
install.sh); `EnergyVad` is a loudness gate over a tracked noise floor, used when the model isn't there.
`TurnDetector` turns frame decisions into "this audio is speech, pass it on" and "the turn ended".
"""

from __future__ import annotations

import logging
from collections import deque
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

RATE = 16000
FRAME = 512                               # samples: 32 ms at 16 kHz, what Silero takes
FRAME_MS = FRAME * 1000 / RATE


class EnergyVad:
    """Speech when a frame is well above the quietest level heard lately."""

    kind = "energy"

    def __init__(self, margin_db: float = 12.0, floor_db: float = -55.0) -> None:
        self.margin, self.min_floor = margin_db, floor_db
        self.noise = floor_db

    def reset(self) -> None:
        self.noise = self.min_floor

    def prob(self, frame: np.ndarray) -> float:
        rms = float(np.sqrt(np.mean(np.square(frame, dtype=np.float32)))) if frame.size else 0.0
        db = 20 * np.log10(max(rms, 1e-6))
        # the floor follows quiet frames quickly and loud ones very slowly
        self.noise = max(self.min_floor, self.noise + (0.2 if db < self.noise else 0.002) * (db - self.noise))
        return float(np.clip((db - self.noise) / (2 * self.margin), 0.0, 1.0))


class SileroVad:
    """Silero VAD (ONNX) on the CPU: one probability per 512-sample frame, with its recurrent state."""

    kind = "silero"
    CONTEXT = 64

    def __init__(self, path: Path) -> None:
        import onnxruntime as ort

        opts = ort.SessionOptions()
        opts.inter_op_num_threads = opts.intra_op_num_threads = 1
        opts.log_severity_level = 3
        self.session = ort.InferenceSession(str(path), sess_options=opts, providers=["CPUExecutionProvider"])
        self.reset()

    def reset(self) -> None:
        self.state = np.zeros((2, 1, 128), dtype=np.float32)
        self.context = np.zeros((1, self.CONTEXT), dtype=np.float32)

    def prob(self, frame: np.ndarray) -> float:
        x = np.concatenate([self.context, frame.reshape(1, -1).astype(np.float32)], axis=1)
        out, self.state = self.session.run(None, {"input": x, "state": self.state, "sr": np.array(RATE, dtype=np.int64)})
        self.context = x[:, -self.CONTEXT:]
        return float(out.reshape(-1)[0])


def make_vad(model: Path | None):
    """Silero when its file and onnxruntime are there, the loudness gate otherwise."""
    if model and model.is_file():
        try:
            return SileroVad(model)
        except Exception as e:                              # a broken file or runtime: still find turn ends
            log.warning("Silero VAD not usable (%s): using the loudness gate", e)
    return EnergyVad()


def vad_kind(model: Path | None) -> str:
    if model and model.is_file():
        try:
            import onnxruntime  # noqa: F401
            return "silero"
        except ImportError:
            pass
    return "energy"


def resample(pcm: np.ndarray, rate: int) -> np.ndarray:
    """int16 at `rate` → float32 in -1…1 at 16 kHz (linear: good enough to detect speech)."""
    x = pcm.astype(np.float32) / 32768.0
    if rate == RATE or not x.size:
        return x
    n = int(round(x.size * RATE / rate))
    return np.interp(np.arange(n) * rate / RATE, np.arange(x.size), x).astype(np.float32)


class TurnDetector:
    """Feed microphone audio; get back what to pass on and when the turn ended.

    `feed(pcm_bytes)` returns a list of ("speech", bytes) and ("end", None). Nothing is passed on while it is
    quiet; once `enter_ms` of speech is heard, the last `preroll_ms` and everything after go out as "speech",
    until `pause_ms` of quiet (or `max_s` of talking) ends the turn.
    """

    def __init__(self, vad, rate: int = RATE, pause_ms: int = 1200, enter_ms: int = 96, preroll_ms: int = 400,
                 max_s: float = 60.0, on: float = 0.5, off: float = 0.35) -> None:
        self.vad, self.rate = vad, rate
        self.pause_ms, self.max_ms, self.on, self.off = pause_ms, max_s * 1000, on, off
        self.enter = max(1, round(enter_ms / FRAME_MS))
        self.step = int(round(FRAME * rate / RATE)) * 2             # bytes of input per VAD frame
        self.ring: deque[bytes] = deque(maxlen=max(1, round(preroll_ms / FRAME_MS)))
        self.reset()

    def reset(self) -> None:
        self.buf = b""
        self.speaking = False
        self.voiced = 0
        self.quiet_ms = 0.0
        self.spoken_ms = 0.0
        self.ring.clear()
        self.vad.reset()

    def begin(self, held: bytes = b"") -> list[tuple[str, bytes | None]]:
        """You are already talking (a barge-in the page heard): pass `held` on and start the turn."""
        self.reset()
        self.speaking = True
        return [("speech", held)] if held else []

    def feed(self, pcm: bytes) -> list[tuple[str, bytes | None]]:
        out: list[tuple[str, bytes | None]] = []
        self.buf += pcm
        while len(self.buf) >= self.step:
            chunk, self.buf = self.buf[:self.step], self.buf[self.step:]
            frame = resample(np.frombuffer(chunk, dtype=np.int16), self.rate)
            frame = np.pad(frame, (0, FRAME - frame.size)) if frame.size < FRAME else frame[:FRAME]
            p = self.vad.prob(frame)
            if not self.speaking:
                self.ring.append(chunk)
                self.voiced = self.voiced + 1 if p >= self.on else 0
                if self.voiced >= self.enter:
                    self.speaking, self.quiet_ms, self.spoken_ms = True, 0.0, 0.0
                    out.append(("speech", b"".join(self.ring)))
                    self.ring.clear()
                continue
            out.append(("speech", chunk))
            self.spoken_ms += FRAME_MS
            self.quiet_ms = 0.0 if p >= self.off else self.quiet_ms + FRAME_MS
            if self.quiet_ms >= self.pause_ms or self.spoken_ms >= self.max_ms:
                out.append(("end", None))
                self.speaking, self.voiced = False, 0
                self.vad.reset()
        return out
