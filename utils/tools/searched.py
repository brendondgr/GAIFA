"""A page the chat's own search found: `web_fetch` of a URL that a `web_search` earlier in the same chat
returned runs without a card, in every mode but Plan (`approvals.decide`, `searched`).

The URL came from the search engine, not from the model, so the model can't hide data in it; asking
for every page a grounded answer reads would only teach the user to click Allow. What counts:

- the same chat (`origin.thread`), one of its last `RECENT` searches that finished;
- the same URL after trivial normalisation only (`normal`): scheme and host in lower case, no default
  port, no fragment, an empty path as "/". No prefix matches: a longer path or another query is
  another URL. Where a URL leads after redirects isn't checked here; the web mod follows them itself;
- and a URL the judge's URL rules (`judge_rules.fetch_rule`) don't flag: one that carries credentials,
  a long encoded value or a private address takes the usual way (a card, or the judge in Auto).

The search results are read back from `tool_calls`, which keeps every call's full result, so the rule
holds across hub restarts with nothing more to store.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit, urlunsplit

if TYPE_CHECKING:
    from utils.db import Database

SEARCH_TOOL = "web_search"
FETCH_TOOL = "web_fetch"
RECENT = 50                      # searches of the chat looked at, newest first
DEFAULT_PORTS = {"http": 80, "https": 443}


def normal(url: Any) -> str | None:
    """The URL with only what can't change the page normalised; None when it isn't an http(s) URL."""
    if not isinstance(url, str):
        return None
    url = url.strip()
    try:
        u = urlsplit(url)
        port = u.port
    except ValueError:
        return None
    scheme, host = u.scheme.lower(), (u.hostname or "")
    if scheme not in DEFAULT_PORTS or not host or u.username is not None or u.password is not None:
        return None
    if ":" in host:
        host = f"[{host}]"                         # IPv6 (hostname drops the brackets)
    netloc = host if port is None or port == DEFAULT_PORTS[scheme] else f"{host}:{port}"
    return urlunsplit((scheme, netloc, u.path or "/", u.query, ""))


def urls_of(result: Any) -> set[str]:
    """The result URLs of one web_search answer, normalised."""
    out: set[str] = set()
    rows = result.get("results") if isinstance(result, dict) else None
    for r in rows if isinstance(rows, list) else []:
        n = normal(r.get("url")) if isinstance(r, dict) else None
        if n:
            out.add(n)
    return out


async def found_by(db: Database, url: Any, thread: Any) -> str | None:
    """The id of the chat's web_search call whose results hold `url`, or None (also when the judge's URL
    rules would flag the URL)."""
    from utils.tools.judge_rules import fetch_rule

    want = normal(url)
    if not want or not isinstance(thread, str) or not thread:
        return None
    if fetch_rule({"url": url}).verdict == "ask":
        return None
    rows = await db.fetchall(
        "SELECT id, result FROM tool_calls WHERE tool = ? AND state = 'done' AND json_extract(origin, '$.thread') = ?"
        " ORDER BY created_ts DESC LIMIT ?", (SEARCH_TOOL, thread, RECENT))
    for r in rows:
        try:
            stored = json.loads(r["result"] or "{}")
        except ValueError:
            continue
        if want in urls_of(stored.get("result") if isinstance(stored, dict) else None):
            return r["id"]
    return None
