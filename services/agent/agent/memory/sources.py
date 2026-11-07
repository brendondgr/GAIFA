"""Other assistants' memories as lines (plan memory-import 1.1).

No assistant hands over its memory as a file of its own (Claude's export does, Phase 3), but every one writes it out
when asked: `EXPORT_PROMPT` (the person's, 2026-11-07, after Claude's own import prompt) asks for five sections and
one `[YYYY-MM-DD] - entry` per line in one code block. `read_lines` reads such an answer without a model:

- a code block: only what is inside it (the "This is the complete set" after it is not an entry);
- `## Instructions`, `**Career**`, `3. **Projects**:`: the section of the lines under it;
- `[2026-06-20] - entry`, `[unknown] - entry`, `2026-06-20 - entry`: an entry and its date;
- `- entry`, `* entry`, `1. entry` (what ChatGPT's Manage memories copies as): an entry without a date;
- a plain line is an entry only when nothing in the text is marked as one (a list pasted as it is), else it is the
  answer's own words ("Here is everything I know:") and left out.

The model only interprets each entry (imports.py).
"""

from __future__ import annotations

import re
from typing import Any

MAX_BYTES = 200_000
MAX_LINES = 1000
SECTIONS = ("instructions", "identity", "career", "projects", "preferences")

EXPORT_PROMPT = """Export all of my stored memories and any context you've learned about me from past conversations. Preserve my words verbatim where possible, especially for instructions and preferences.

## Categories (output in this order):

1. **Instructions**: Rules I've explicitly asked you to follow going forward — tone, format, style, "always do X", "never do Y", and corrections to your behavior. Only include rules from stored memories, not from conversations.

2. **Identity**: Name, age, location, education, family, relationships, languages, and personal interests.

3. **Career**: Current and past roles, companies, and general skill areas.

4. **Projects**: Projects I meaningfully built or committed to. Ideally ONE entry per project. Include what it does, current status, and any key decisions. Use the project name or a short descriptor as the first words of the entry.

5. **Preferences**: Opinions, tastes, and working-style preferences that apply broadly.

## Format:

Use section headers for each category. Within each category, list one entry per line, sorted by oldest date first. Format each line as:

[YYYY-MM-DD] - Entry content here.

If no date is known, use [unknown] instead.

## Output:
- Wrap the entire export in a single code block for easy copying.
- After the code block, state whether this is the complete set or if more remain."""

_FENCE = re.compile(r"^\s*(```|~~~)")
_HEADER = re.compile(r"^\s*(?:#{1,6}\s*(?P<h>.+?)\s*#*\s*$|(?:\d+[.)]\s*)?\*\*(?P<b>[^*]+?)\*\*\s*:?\s*$)")
_LEADING_BOLD = re.compile(r"^\s*(?:\d+[.)]\s*)?\*\*(?P<b>[^*]+?)\*\*\s*:\s*(?P<rest>.+)$")   # "1. **Instructions**: Rules…"
_DATED = re.compile(r"^\[?\s*(?P<d>\d{4}-\d{2}-\d{2}|unknown|n/?a|\?+|no date)\s*\]?\s*[-–—:]\s*(?P<t>.+)$", re.I)
_BRACKETED = re.compile(r"^\[(?P<d>[^\]]{0,20})\]\s*[-–—:]?\s*(?P<t>.+)$")
_BULLET = re.compile(r"^\s*(?:[-*•+]|\d+[.)])\s+(?P<t>.+)$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def section_of(header: str) -> str:
    """A header as a section: one of SECTIONS when it names one ("Personal identity" → identity), else its words."""
    words = re.sub(r"[^\w\s/&-]", " ", header).strip().lower()
    for s in SECTIONS:
        if s in words or s.rstrip("s") in words.split():
            return s
    return re.sub(r"\s+", " ", words)[:40] or "other"


def _inside_fences(rows: list[str]) -> list[str]:
    """The lines inside code blocks, when the text has one; else all of them."""
    if not any(_FENCE.match(r) for r in rows):
        return rows
    out, inside = [], False
    for r in rows:
        if _FENCE.match(r):
            inside = not inside
            continue
        if inside:
            out.append(r)
    return out


def read_lines(text: str) -> list[dict[str, Any]]:
    """Each entry of an assistant's memory export: `{n, section, date, text}` (n from 1; section None before any
    header; date "YYYY-MM-DD" or None). The same entry twice is read once."""
    rows = _inside_fences((text or "").replace("\r\n", "\n").split("\n"))
    found: list[tuple[str | None, str | None, str, bool]] = []      # section, date, text, marked as an entry
    section: str | None = None
    for raw in rows:
        line = raw.strip()
        if not line:
            continue
        h = _HEADER.match(line)
        if h and not _DATED.match(line):
            section = section_of(h.group("h") or h.group("b"))
            continue
        lb = _LEADING_BOLD.match(line)
        if lb and section_of(lb.group("b")) in SECTIONS:              # the prompt's own list pasted back: a header
            section = section_of(lb.group("b"))
            continue
        b = _BULLET.match(line)
        body, marked = (b.group("t").strip(), True) if b else (line, False)
        date = None
        d = _DATED.match(body) or _BRACKETED.match(body)
        if d:
            body, marked = d.group("t").strip(), True
            date = d.group("d").strip() if _DATE.match(d.group("d").strip()) else None
        if body.strip("-–—*:. "):
            found.append((section, date, body, marked))
    any_marked = any(m for *_, m in found)
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for section, date, body, marked in found:
        key = re.sub(r"\s+", " ", body.lower())
        if (any_marked and not marked) or key in seen:
            continue
        seen.add(key)
        out.append({"n": len(out) + 1, "section": section, "date": date, "text": re.sub(r"\s+", " ", body)})
    return out
