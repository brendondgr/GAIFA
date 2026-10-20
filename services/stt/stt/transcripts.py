"""A transcript's shapes, and saving it as one folder output (architecture §4.7).

``outputs/stt/<date>/<HHMMSS>-<slug>/`` holds ``transcript.md`` (the main file: paragraphs marked
``[mm:ss]``), ``transcript.srt`` (one cue per segment), ``words.json`` (the whole result with word
times) and ``output.json`` (the sidecar, ``complete`` once all three are written). A folder because
the hub reads ``<stem>.json`` beside ``<stem>.md`` as that file's sidecar, not as an output.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from .segment import Segment

#: A new paragraph after a silence this long, or once a paragraph has run this long.
PARAGRAPH_GAP_S = 2.0
PARAGRAPH_MAX_S = 60.0


def result(segments: list[Segment], *, duration: float, language: str | None, model: str,
           timestamps: str = "segments") -> dict[str, Any]:
    """The job's result: ``{text, language, duration, model, segments[{start, end, text, words?}]}``."""
    rows = []
    for seg in segments:
        row: dict[str, Any] = {"start": round(seg.start, 2), "end": round(seg.end, 2), "text": seg.text}
        if timestamps == "words":
            row["words"] = [{"text": w.text, "start": round(w.start, 2), "end": round(w.end, 2),
                             "p": None if w.confidence is None else round(w.confidence, 3)} for w in seg.words]
        rows.append(row)
    out: dict[str, Any] = {"text": " ".join(s.text for s in segments).strip(), "language": language,
                           "duration": round(duration, 2), "model": model}
    if timestamps != "none":
        out["segments"] = rows
    return out


def stamp(seconds: float) -> str:
    """``mm:ss``, or ``h:mm:ss`` from an hour on."""
    s = int(max(0.0, seconds))
    h, m, sec = s // 3600, s % 3600 // 60, s % 60
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m:02d}:{sec:02d}"


def paragraphs(segments: list[Segment]) -> list[tuple[float, str]]:
    """Segments grouped into paragraphs at pauses: ``[(start, text)]``."""
    out: list[tuple[float, list[str]]] = []
    last_end = None
    for seg in segments:
        if (not out or last_end is None or seg.start - last_end >= PARAGRAPH_GAP_S
                or seg.end - out[-1][0] > PARAGRAPH_MAX_S):
            out.append((seg.start, []))
        out[-1][1].append(seg.text)
        last_end = seg.end
    return [(start, " ".join(texts)) for start, texts in out]


def markdown(segments: list[Segment], *, title: str, duration: float, model: str, language: str | None) -> str:
    head = f"# {title}\n\n_Transcript: {stamp(duration)} of audio, {model}" + (f", language {language}" if language else "") + "._\n"
    if not segments:
        return head + "\n_(no speech found)_\n"
    return head + "".join(f"\n[{stamp(start)}] {text}\n" for start, text in paragraphs(segments))


def srt(segments: list[Segment]) -> str:
    def t(x: float) -> str:
        ms = int(round(max(0.0, x) * 1000))
        return f"{ms // 3_600_000:02d}:{ms // 60_000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"
    return "".join(f"{i}\n{t(s.start)} --> {t(s.end)}\n{s.text}\n\n" for i, s in enumerate(segments, 1))


def slug(text: str, limit: int = 40) -> str:
    words = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (words[:limit].rstrip("-") or "transcript")


def save(outputs: Path, segments: list[Segment], res: dict[str, Any], *, title: str,
         source: dict[str, Any] | None = None, now: float | None = None) -> Path:
    """Write the folder output; returns its path. ``output.json`` says complete only at the end."""
    when = time.localtime(now if now is not None else time.time())
    day = outputs / time.strftime("%Y-%m-%d", when)
    folder = day / f"{time.strftime('%H%M%S', when)}-{slug(title)}"
    n = 2
    while folder.exists():
        folder = day / f"{time.strftime('%H%M%S', when)}-{slug(title)}-{n}"
        n += 1
    folder.mkdir(parents=True)
    side = {"title": f"Transcript: {title}", "kind": "text", "main": "transcript.md",
            "model": res.get("model"), "params": {"language": res.get("language")},
            "duration": res.get("duration"), "source": source or {}, "complete": False}
    _write(folder / "output.json", json.dumps(side, indent=1))
    full = result(segments, duration=res.get("duration") or 0.0, language=res.get("language"),
                  model=res.get("model") or "", timestamps="words")
    _write(folder / "transcript.md", markdown(segments, title=title, duration=res.get("duration") or 0.0,
                                               model=res.get("model") or "", language=res.get("language")))
    _write(folder / "transcript.srt", srt(segments))
    _write(folder / "words.json", json.dumps(full, ensure_ascii=False, indent=1))
    side["complete"] = True
    _write(folder / "output.json", json.dumps(side, indent=1))
    return folder


def _write(path: Path, text: str) -> None:
    part = path.with_name(path.name + ".part")
    part.write_text(text, encoding="utf-8")
    part.replace(path)
