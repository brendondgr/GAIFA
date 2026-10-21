"""Screening reports kept with an output, so a page screened once isn't screened again (plan 30.6, 30.8).

The web page route (`utils/routes/webpages.py`) screens a whole page and keeps the report next to the output's
cached text, at `outputs/.text/<id>.screening.json` (`text.forget` removes it with the output). A report is used
again only for the same text (its SHA-256), screened with the same model and settings (`ScreenConfig.key()`), and
only when the model answered (`patterns+model`); it covers the first `covered` characters. `apply` turns it into
the screened version of any window of that text: the lines of a removed passage become `[removed by screening: …]`
and blank lines, as `screen()` writes them, so line numbers and citations hold.

`screened_window` is what the readers call (`hub_read_document`, `GET /api/outputs/{id}/text?screened=true`): the
stored report when it fits the window, else the window screened on its own.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any

from utils.outputs.text import TEXT_DIR
from utils.tools import screen as sc

log = logging.getLogger("aihub.tools")

VERSION = 1
MAX_WHOLE = 400_000          # characters of a page the route screens at once; the rest is screened as it's read


def report_file(outputs: Path, oid: str) -> Path:
    return outputs / TEXT_DIR / f"{oid}.screening.json"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()


def save(outputs: Path, oid: str, text: str, s: sc.Screened, key: str) -> dict[str, Any]:
    """Keep the report for `text` (the first `len(text)` characters of the output's text). Blocking."""
    starts = [0]
    for line in text.split("\n"):
        starts.append(starts[-1] + len(line) + 1)
    rep = {"v": VERSION, "sha": _sha(text), "covered": len(text), "key": key, "checked": s.checked, "ms": s.ms,
           "findings": [{"passage": f.passage, "why": f.why, "by": f.by, "excerpt": f.excerpt, "lines": list(f.lines),
                         "start": starts[f.lines[0]], "end": starts[f.lines[1]] - 1} for f in s.findings]}
    f = report_file(outputs, oid)
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_name(f.name + ".part")
        tmp.write_text(json.dumps(rep, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, f)
    except OSError as e:
        log.warning("screening report for %s: %s", oid, e)
    return rep


def load(outputs: Path, oid: str, text: str, key: str) -> dict[str, Any] | None:
    """The stored report when it was made for this text with this model and the model answered, else None. Blocking."""
    try:
        rep = json.loads(report_file(outputs, oid).read_text(encoding="utf-8"))
        ok = (rep.get("v") == VERSION and rep.get("key") == key and rep.get("checked") == "patterns+model"
              and isinstance(rep.get("covered"), int) and rep["covered"] <= len(text)
              and rep.get("sha") == _sha(text[:rep["covered"]]))
        return rep if ok else None
    except (OSError, ValueError, TypeError, AttributeError):
        return None


def apply(rep: dict[str, Any], window: str, start: int) -> sc.Screened | None:
    """The screened version of `window` (the output's text from character `start`), or None when the report
    doesn't cover all of it."""
    if start + len(window) > rep["covered"]:
        return None
    lines = window.split("\n")
    at, begins = start, []
    for line in lines:
        begins.append(at)                 # where each line of the window begins in the whole text
        at += len(line) + 1
    out, hit = list(lines), []
    for f in rep["findings"]:             # a passage spans whole lines: start (its first) to end (its last newline)
        first = True
        for i, a in enumerate(begins):
            if f["start"] <= a <= f["end"]:
                out[i] = f"[removed by screening: {f['why']}]" if first else ""
                first = False
        if not first:
            hit.append(sc.Finding(f["passage"], f["why"], f["by"], f.get("excerpt", ""), tuple(f.get("lines") or (0, 0))))
    return sc.Screened("\n".join(sc.HIDDEN_CHARS.sub("", line) for line in out), hit, rep["checked"], 0.0)


async def screen_whole(outputs: Path, config: Any, oid: str, text: str, kind: str) -> tuple[sc.Screened | None, dict[str, Any] | None]:
    """Screen the output's text (its first MAX_WHOLE characters) and keep the report; reuse a kept one.
    (None, None) when `[agent.screen]` doesn't cover this kind."""
    if not sc.covers(config, kind) or not text.strip():
        return None, None
    part = text[:MAX_WHOLE]
    if MAX_WHOLE < len(text):
        nl = part.rfind("\n")
        part = part[: nl + 1] if nl > 0 else part
    key = sc.screen_config(config).key()
    rep = await asyncio.to_thread(load, outputs, oid, text, key)
    if rep is not None and rep["covered"] >= len(part):
        s = apply(rep, part, 0)
        if s is not None:
            s.ms = rep.get("ms", 0.0)
            return s, rep
    s = await sc.screen_for(config, part, kind, whole=True)
    if s is None:
        return None, None
    rep = await asyncio.to_thread(save, outputs, oid, part, s, key)
    return s, rep


async def screened_window(outputs: Path, config: Any, oid: str, text: str, window: str, start: int, kind: str) -> sc.Screened | None:
    """A window of an output's text as the chat model may read it: from the kept report when it covers the window,
    else screened now. None when `[agent.screen]` doesn't cover this kind."""
    if not sc.covers(config, kind) or not window.strip():
        return None
    rep = await asyncio.to_thread(load, outputs, oid, text, sc.screen_config(config).key())
    s = apply(rep, window, start) if rep is not None else None
    return s if s is not None else await sc.screen_for(config, window, kind)
