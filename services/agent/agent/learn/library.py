"""The learner's library (plan 22.5): what earlier rounds learned, per domain, for the next round.

    data/agent/learn/library/<domain>/INDEX.md                  one line per entry: its cue
    data/agent/learn/library/<domain>/entries/<run>/EXPERIENCE.md  cue, lesson, evidence, confidence
    data/agent/learn/library/<domain>/entries/<run>/adopted.diff   what was adopted (may be empty)

Only the improver reads it; the live agent never does (Harness²: inheriting edits without probing
them made things worse).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

FIELDS = ("cue", "lesson", "evidence", "confidence")


class Library:
    def __init__(self, data: Path | str, domain: str) -> None:
        self.dir = Path(data) / "learn" / "library" / domain
        self.domain = domain

    def entries(self) -> list[str]:
        d = self.dir / "entries"
        return sorted(p.name for p in d.iterdir() if p.is_dir()) if d.is_dir() else []

    def add(self, run: str, exp: dict[str, Any], diff: str = "", adopted: str = "") -> Path | None:
        if not all(isinstance(exp.get(k), str) and exp[k].strip() for k in ("cue", "lesson", "evidence")):
            return None
        d = self.dir / "entries" / run
        d.mkdir(parents=True, exist_ok=True)
        lines = [f"# {self.domain} · {run}", "", f"- adopted: {adopted or 'nothing'}", ""]
        lines += [f"- **{k}**: {str(exp[k]).strip()}" for k in FIELDS if exp.get(k)]
        (d / "EXPERIENCE.md").write_text("\n".join(lines) + "\n")
        (d / "adopted.diff").write_text(diff)
        self.rebuild()
        return d

    def _field(self, run: str, name: str) -> str:
        f = self.dir / "entries" / run / "EXPERIENCE.md"
        for line in (f.read_text().splitlines() if f.is_file() else []):
            if line.startswith(f"- **{name}**:"):
                return line.split(":", 1)[1].strip()
        return ""

    def rebuild(self) -> Path:
        rows = [f"# Library: {self.domain}", "", "Lessons from earlier improvement rounds in this area. Open an entry when its cue fits.", ""]
        names = self.entries()
        rows += [f"- `entries/{n}/`: {self._field(n, 'cue')}" for n in names] or ["(empty: the first round in this area)"]
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "INDEX.md").write_text("\n".join(rows) + "\n")
        return self.dir / "INDEX.md"

    def text(self, limit: int = 6) -> str:
        """The newest entries in full, for a prompt."""
        names = self.entries()[-limit:]
        if not names:
            return "(none yet)"
        return "\n\n".join((self.dir / "entries" / n / "EXPERIENCE.md").read_text() for n in names)

    def listing(self) -> list[dict[str, Any]]:
        return [{"run": n, **{k: self._field(n, k) for k in FIELDS}} for n in self.entries()]
