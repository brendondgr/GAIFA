"""The learner's library (plan 22.5): what earlier rounds learned, per domain, for the next round.

    data/agent/learn/library/<domain>/INDEX.md                  one line per entry: its cue
    data/agent/learn/library/<domain>/entries/<run>/EXPERIENCE.md  cue, lesson, evidence, confidence
    data/agent/learn/library/<domain>/entries/<run>/adopted.diff   what was adopted (may be empty)

Only the improver reads it; the live agent never does (Harness²: inheriting edits without probing
them made things worse).

An entry whose change went live (adopted, or proposed and then approved) is withdrawn once that
version is rejected or no longer in the active harness (rolled back): its lesson didn't hold, so the
editors stop reading it. Withdrawal is worked out on each read, so activating the version again brings
the lesson back. Lessons from rounds that kept the harness or failed the gate never go stale.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..harness import Harness, HarnessError

FIELDS = ("cue", "lesson", "evidence", "confidence")


class Library:
    def __init__(self, data: Path | str, domain: str) -> None:
        self.dir = Path(data) / "learn" / "library" / domain
        self.domain = domain

    def entries(self) -> list[str]:
        d = self.dir / "entries"
        return sorted(p.name for p in d.iterdir() if p.is_dir()) if d.is_dir() else []

    def add(self, run: str, exp: dict[str, Any], diff: str = "", adopted: str = "", version: int | None = None) -> Path | None:
        if not all(isinstance(exp.get(k), str) and exp[k].strip() for k in ("cue", "lesson", "evidence")):
            return None
        d = self.dir / "entries" / run
        d.mkdir(parents=True, exist_ok=True)
        lines = [f"# {self.domain} · {run}", "", f"- adopted: {adopted or 'nothing'}"]
        lines += [f"- version: {version}", ""] if version else [""]
        lines += [f"- **{k}**: {str(exp[k]).strip()}" for k in FIELDS if exp.get(k)]
        (d / "EXPERIENCE.md").write_text("\n".join(lines) + "\n")
        (d / "adopted.diff").write_text(diff)
        self.rebuild()
        return d

    def _field(self, run: str, name: str) -> str:
        f = self.dir / "entries" / run / "EXPERIENCE.md"
        for line in (f.read_text().splitlines() if f.is_file() else []):
            if line.startswith((f"- **{name}**:", f"- {name}:")):
                return line.split(":", 1)[1].strip()
        return ""

    def version(self, run: str) -> int | None:
        """The harness version the entry's round composed: its own line, or (entries written before it had
        one) the run's record in data/agent/learn/runs/."""
        v = self._field(run, "version")
        if v.isdigit():
            return int(v)
        try:
            rec = json.loads((self.dir.parents[1] / "runs" / f"{run}.json").read_text())
        except (OSError, ValueError):
            return None
        return next((d.get("final") for d in rec.get("domains") or [] if d.get("domain") == self.domain and d.get("final")), None)

    def withdrawn(self, run: str) -> str | None:
        """Why the entry's lesson no longer holds (its live change was rejected or rolled back), or None."""
        if self._field(run, "adopted") not in ("adopted", "proposed"):
            return None
        n = self.version(run)
        if not n:
            return None
        h = Harness(self.dir.parents[2])
        try:
            by = h.meta(n).get("adopted_by")
            live = n in h.chain(h.current())
        except HarnessError:
            return f"version {n} is gone"
        if by == "rejected":
            return f"version {n} was rejected"
        if by in ("auto", "user") and not live:
            return f"version {n} was rolled back"
        return None

    def rebuild(self) -> Path:
        rows = [f"# Library: {self.domain}", "", "Lessons from earlier improvement rounds in this area. Open an entry when its cue fits.", ""]
        names = self.entries()
        rows += [f"- `entries/{n}/`: {self._field(n, 'cue')}" + (f" (withdrawn: {w})" if (w := self.withdrawn(n)) else "")
                 for n in names] or ["(empty: the first round in this area)"]
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "INDEX.md").write_text("\n".join(rows) + "\n")
        return self.dir / "INDEX.md"

    def text(self, limit: int = 6) -> str:
        """The newest entries that still hold, in full, for a prompt (the index is brought up to date too)."""
        if self.entries():
            self.rebuild()
        names = [n for n in self.entries() if not self.withdrawn(n)][-limit:]
        if not names:
            return "(none yet)"
        return "\n\n".join((self.dir / "entries" / n / "EXPERIENCE.md").read_text() for n in names)

    def listing(self) -> list[dict[str, Any]]:
        return [{"run": n, **{k: self._field(n, k) for k in FIELDS}, "version": self.version(n), "withdrawn": self.withdrawn(n)}
                for n in self.entries()]
