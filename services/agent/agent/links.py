"""The http(s) links in what the user typed (plan: links in the prompt are read directly).

The agent sends them with a `web_fetch` call as `origin.links`; the hub lets a fetch of exactly one of them run without
a card (`utils/tools/searched.py`, `shared`). Only the user's own words count (`context.said`: the text and the replies
to quoted parts), never tool results, attachments or the quoted parts.
"""

from __future__ import annotations

import re
from typing import Any

URL = re.compile(r"https?://[^\s<>\"'`\[\]{}|\\^]+", re.I)
TRAIL = ".,;:!?*_~'\""
MAX = 200


def links_in(text: str) -> list[str]:
    """The URLs in `text`, as typed: `<…>` and markdown links work; trailing punctuation and an unbalanced `)` are
    not part of the URL."""
    out: list[str] = []
    for m in URL.finditer(text or ""):
        u = m.group(0)
        while u:
            if u[-1] in TRAIL:
                u = u[:-1]
            elif u[-1] == ")" and u.count(")") > u.count("("):
                u = u[:-1]
            else:
                break
        if len(u) > len("https://") and u not in out:
            out.append(u)
    return out


def user_links(said: list[str]) -> list[str]:
    """The links in the user's messages, newest message first, at most MAX."""
    out: list[str] = []
    for words in reversed(said):
        for u in links_in(words):
            if u not in out:
                out.append(u)
    return out[:MAX]


def of_events(events: list[dict[str, Any]]) -> list[str]:
    from . import context as ctx

    return user_links([ctx.said(e.get("payload")) for e in events if e.get("type") == "user"])
