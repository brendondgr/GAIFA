"""A project chat's prompt parts (plan projects 3.3, 4.1): the project itself, its knowledge and its skills.

- **`project`** (after AGENT.md): the project's name, description and instructions (the user's own words).
- **`project_knowledge`** (after Skills): the files and pages. *Inline* while all their text fits `project_share` (default
  0.25, Settings → Agent → Documents) of the model's window, counted as docs.py counts (4 characters a token): each
  source whole, inside `<untrusted>`, with its title, kind, URL and, for a page, how old its copy is. *Listed* past that:
  one line per source and how to search and read them (`project_search`, `project_read`).
- **Skills this project uses** (4.1): the bodies of the project's `defaults.skills`, up to SKILLS_MAX characters in all;
  the rest are listed first among the skills.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from .. import context as ctx
from . import sources

log = logging.getLogger("agent.projects")
SHARE = 0.25
SKILLS_MAX = 8000


def share(agent: Any) -> float:
    from ..docs import load
    try:
        return float(load(agent.cfg.data, agent.cfg).get("project_share") or SHARE)
    except Exception:  # noqa: BLE001
        return SHARE


def project_text(p: dict[str, Any]) -> str:
    out = [f"This chat is part of the project **{p['name']}**."]
    if (p.get("description") or "").strip():
        out.append(p["description"].strip())
    if (p.get("instructions") or "").strip():
        out.append("The project's instructions (the user's, for every chat in it):\n" + p["instructions"].strip())
    return "\n\n".join(out)


def _where(src: dict[str, Any], now: float) -> str:
    bits = [src["kind"]]
    if src.get("url"):
        bits.append(src["url"])
    if src["kind"] == "page":
        if src.get("fetched"):
            bits.append(f"fetched {sources.age_words(now - src['fetched'])} ago")
        if src.get("status") == "error":
            bits.append(f"the last fetch failed: {src.get('error') or 'unknown error'}; this is the last copy")
    return ", ".join(bits)


def line_of(src: dict[str, Any], now: float) -> str:
    size = f"~{int(src.get('chars') or 0) // 4:,} tokens"
    return f"- {src['id']}: {ctx.label(src.get('title') or src['id'], 200)} ({_where(src, now)}; {size})"


async def project_knowledge(agent: Any, pid: str, window: int, now: float | None = None) -> dict[str, Any]:
    """`{mode: 'inline' | 'listed' | 'none', text, tokens}` for the project's sources."""
    now = now or time.time()
    srcs = [s for s in agent.projects.sources(pid) if s.get("output_id")]
    if not srcs:
        return {"mode": "none", "text": "", "tokens": 0}
    budget = int(share(agent) * window)
    total = sum(int(s.get("chars") or 0) for s in srcs) // 4
    if total <= budget:
        try:
            blocks = []
            for s in srcs:
                body = await sources.text(agent, s)
                blocks.append(f"{s['id']} ({_where(s, now)}): cite it as {s['id']}:N (a line)\n"
                              + ctx.untrusted(f"{s['id']} {s.get('title') or ''}", ctx.numbered(body)))
            text = (f"The project's files and pages, whole ({len(srcs)}; {ctx.DATA_NOTE})\n\n" + "\n\n".join(blocks))
            return {"mode": "inline", "text": text, "tokens": ctx.est(text)}
        except Exception as e:  # noqa: BLE001: listed, then: the tools read them
            log.info("project %s's sources whole: %s", pid, e)
    lines = [line_of(s, now) for s in srcs]
    text = (f"The project's files and pages ({len(srcs)}, ~{total:,} tokens: too many to include whole):\n" + "\n".join(lines)
            + "\nSearch them with project_search(query) and read one with project_read(source, offset?); cite a passage as "
              "src_…:line.")
    return {"mode": "listed", "text": text, "tokens": ctx.est(text)}
