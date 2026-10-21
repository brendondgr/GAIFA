"""The fake web (plan 26.2): what search and fetch answer in a dry run (the agent eval), so an eval
never reaches the internet. The hub sends `dry_run` in `X-AIHub-Origin` because the tools say
`dry_run = true` in `[tools]`.

`fakeweb/search.json` lists results, each with `keywords`: a search returns the results that share
a keyword with the query (all of them when none do). `fakeweb/pages.json` maps URLs to files in
`fakeweb/pages/` and their content type. Its hosts are under `.example`, which never resolves, so
the same URLs fail for real.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from safety import Fetched

HERE = Path(__file__).resolve().parent / "fakeweb"


def is_dry_run(origin_header: str | None) -> bool:
    try:
        return bool(json.loads(origin_header or "{}").get("dry_run"))
    except (ValueError, AttributeError):
        return False


@dataclass
class FakeWeb:
    results: list[dict[str, Any]]
    pages: dict[str, dict[str, str]]
    base: Path

    @classmethod
    def load(cls, base: Path = HERE) -> FakeWeb:
        return cls(json.loads((base / "search.json").read_text()), json.loads((base / "pages.json").read_text()), base)

    def search(self, query: str, limit: int) -> list[dict[str, Any]]:
        words = set(re.findall(r"[a-z0-9]+", query.lower()))
        hits = [r for r in self.results if words & {k.lower() for k in r.get("keywords", [])}] or self.results
        return [{k: v for k, v in r.items() if k != "keywords"} for r in hits[:limit]]

    def fetch(self, url: str) -> Fetched | None:
        page = self.pages.get(url) or self.pages.get(url.rstrip("/"))
        if page is None:
            return None
        ctype = page.get("content_type", "text/html")
        return Fetched(url, 200, ctype, "utf-8", (self.base / "pages" / page["file"]).read_bytes())
