"""What the chat model reads of a fetched page (`web_fetch`'s result, shaped by the hub after the web mod saved it).

- **Numbered lines.** The text carries the saved page's own line numbers (`  120| …`, as `hub_read_document` gives
  them; blank lines left out), so a passage can be cited as `#n:120` and the chat opens the viewer there. The result's
  `cite` says how, with `#n` for the output's ref (the agent puts the real one in).
- **Relevant passages first.** A page longer than the call's `max_chars` used to reach the model as its first
  `max_chars`. Now, with a question (the call's `focus`, else the user's message this turn, which the agent sends as
  `origin.question` and the hub never stores), its passages are scored and the best ones are returned, most relevant
  first, each under a `── lines a–b · under "<heading>" ──` line, up to `max_chars`, with a one-line "About this page"
  (the page's description, else its first paragraph). `[agent.web] relevance`: `lexical` (words in common, BM25),
  `decide` (the decide mod answers "does this passage help answer …?" for lexical's best `candidates`, a few at once;
  lexical's order if it doesn't answer in `timeout_s`), `auto` (decide when the decide mod is up with its model loaded,
  else lexical: it never loads a model for this), `off`. A short page, no question, or no passage in common: the page's
  start, as before.
- **Screened after choosing.** Only what the model will read is screened (`screen.screen_for`), on a copy of the page
  where every other line is blank, so line numbers and the screening's removal lines stay where they are.

The whole page stays the output, for `hub_read_document` and `hub_search_document`.
"""

from __future__ import annotations

from utils.config import on_this_hub

import asyncio
import math
import re
import time
from collections import Counter, OrderedDict
from typing import TYPE_CHECKING, Any
from urllib.parse import quote, urlsplit

import httpx

from . import screen as screen_mod

if TYPE_CHECKING:
    from utils.server import Hub

FETCH_TOOL = "web_fetch"
DEFAULT_MAX = 6000
PRIVATE = ("said", "question", "links", "narration")   # the user's words (and the agent's text for the judge): read by the hub, never stored
_QUESTIONS: OrderedDict[tuple[str, Any], str] = OrderedDict()
KEEP_QUESTIONS = 256
WORD = re.compile(r"[^\W_]+(?:['’][^\W_]+)?")
STOP = set("""a about above after again against all am an and any are as at be because been before being below between
both but by can could did do does doing down during each few for from further had has have having he her here hers him
his how i if in into is it its itself just me more most my no nor not now of off on once only or other our ours out over
own same she should so some such than that the their them then there these they this those through to too under until
up very was we were what when where which while who whom why will with would you your yours tell show give find get
know want need please explain describe page site web""".split())
K1, B = 1.2, 0.75
SUMMARY_CHARS = 300
DECIDE_QUESTION = "Does this passage help answer the question: {q}"


# ---- the question ---------------------------------------------------------------------------

def note_question(origin: dict[str, Any] | None) -> None:
    """Keep the user's question of a web_fetch call in memory (by chat and turn), so the call's result can be shaped
    by it, also after an approval card. Never written to the database."""
    q = (origin or {}).get("question")
    thread = (origin or {}).get("thread")
    if isinstance(q, str) and q.strip() and isinstance(thread, str):
        key = (thread, (origin or {}).get("turn"))
        _QUESTIONS[key] = q.strip()[:2000]
        _QUESTIONS.move_to_end(key)
        while len(_QUESTIONS) > KEEP_QUESTIONS:
            _QUESTIONS.popitem(last=False)


def question_for(origin: dict[str, Any] | None) -> str | None:
    return _QUESTIONS.get(((origin or {}).get("thread"), (origin or {}).get("turn")))


def private_out(origin: dict[str, Any] | None) -> dict[str, Any] | None:
    """The origin without the user's words (the judge's `said`, the question, the links)."""
    if origin and any(k in origin for k in PRIVATE):
        return {k: v for k, v in origin.items() if k not in PRIVATE}
    return origin


# ---- passages -------------------------------------------------------------------------------

def body_start(lines: list[str]) -> int:
    """The first line after the web mod's header (`# Title`, Source, Fetched, Published, `---`), else 0."""
    head = lines[:10]
    if any(x.startswith("Source: <") for x in head) and "---" in head:
        return head.index("---") + 1
    return 0


def blocks(lines: list[str], start: int = 0) -> list[tuple[int, int, str]]:
    """(first line, last line + 1, the heading it's under) of each passage after `start`; a heading alone joins the
    passage after it."""
    text = "\n".join(lines)
    spans = [(a, b) for a, b in screen_mod.passages(text) if a >= start]
    code = screen_mod.code_lines(lines)
    out: list[tuple[int, int, str]] = []
    heading, pending = "", None
    for a, b in spans:
        first = lines[a].lstrip()
        if b - a == 1 and first.startswith("#") and a not in code:
            heading = re.sub(r"^#+\s*", "", first).strip()
            pending = a if pending is None else pending
            continue
        out.append((pending if pending is not None else a, b, heading))
        pending = None
    if pending is not None:
        out.append((pending, len(lines), heading))
    return out


def terms(text: str) -> list[str]:
    out = []
    for w in WORD.findall(text.lower()):
        w = w.replace("’", "'")
        if w in STOP or (len(w) < 2 and not w.isdigit()):
            continue
        for suf in ("'s", "ies", "es", "s"):            # plural and possessive, lightly
            if w.endswith(suf) and len(w) - len(suf) >= 3:
                w = w[: -len(suf)] + ("y" if suf == "ies" else "")
                break
        out.append(w)
    return out


def lexical(query: str, texts: list[str], headings: list[str] | None = None) -> list[float]:
    """BM25 of each text for the query's words (its heading counts too)."""
    q = set(terms(query))
    if not q or not texts:
        return [0.0] * len(texts)
    docs = [terms(t) + terms((headings or [""] * len(texts))[i]) for i, t in enumerate(texts)]
    n = len(docs)
    avg = sum(len(d) for d in docs) / n or 1.0
    df = Counter(t for d in docs for t in set(d) if t in q)
    idf = {t: math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5)) for t in df}
    out = []
    for d in docs:
        tf = Counter(t for t in d if t in idf)
        out.append(sum(idf[t] * f * (K1 + 1) / (f + K1 * (1 - B + B * len(d) / avg)) for t, f in tf.items()))
    return out


async def decide_scores(cfg: Any, query: str, texts: list[str], idx: list[int],
                        client: httpx.AsyncClient, parallel: int = screen_mod.PARALLEL) -> dict[int, float]:
    """P(yes) that each passage in `idx` helps answer `query`, from the decide mod."""
    from .judge import defuse

    sem = asyncio.Semaphore(parallel)
    question = DECIDE_QUESTION.format(q=re.sub(r"\s+", " ", query).strip()[:400])

    async def one(i: int) -> tuple[int, float]:
        async with sem:
            r = await client.post(f"{(on_this_hub(cfg.url) or cfg.url).rstrip('/')}/v1/decide", json={
                "input": defuse(texts[i][:3000]), "model": cfg.model,
                "questions": [{"id": "relevant", "type": "yesno", "question": question}]})
            r.raise_for_status()
            return i, float(r.json()["answers"]["relevant"]["probs"]["yes"])
    return dict(await asyncio.gather(*(one(i) for i in idx)))


def backend(hub: Hub) -> str:
    """`[agent.web] relevance` as it applies now: auto → decide only while the decide mod is up with a model loaded."""
    mode = hub.config.agent.web.relevance
    if mode != "auto":
        return mode
    try:
        svc = hub.services.get("decide")
    except Exception:  # noqa: BLE001: no decide mod
        return "lexical"
    return "decide" if svc.up and getattr(svc, "load", None) == "loaded" else "lexical"


async def rank(hub: Hub, query: str, lines: list[str], bl: list[tuple[int, int, str]], how: str,
               client: httpx.AsyncClient | None = None) -> tuple[list[float], str]:
    """Each block's score (0: not relevant) and what scored them."""
    texts = ["\n".join(lines[a:b]) for a, b, _ in bl]
    lex = lexical(query, texts, [h for _, _, h in bl])
    if how != "decide":
        return lex, "lexical"
    wc = hub.config.agent.web
    order = sorted(range(len(bl)), key=lambda i: -lex[i])
    cand = [i for i in order if lex[i] > 0][: wc.candidates] or list(range(min(len(bl), wc.candidates)))
    own = client is None
    client = client or httpx.AsyncClient(trust_env=False, timeout=httpx.Timeout(wc.timeout_s + 1))
    try:
        got = await asyncio.wait_for(decide_scores(wc, query, texts, cand, client), wc.timeout_s)
    except (asyncio.TimeoutError, httpx.HTTPError, ValueError, KeyError, TypeError):
        return lex, "lexical (the decide mod didn't answer)"
    finally:
        if own:
            await client.aclose()
    top = max(lex) or 1.0
    # decide's yes decides; lexical breaks ties. A passage decide says no to (p < 0.5) is left out.
    return [got[i] + 0.01 * lex[i] / top if got.get(i, 0) >= 0.5 else 0.0 for i in range(len(bl))], "decide"


def choose(bl: list[tuple[int, int, str]], scores: list[float], lines: list[str], budget: int) -> list[tuple[int, int, str, float]]:
    """The best blocks that fit `budget` characters, each with the block after it when that fits too (context), merged
    where they touch; most relevant first. A best block longer than the budget is cut to it."""
    size = [sum(len(x) + 6 for x in lines[a:b] if x.strip()) for a, b, _ in bl]
    picked: dict[int, float] = {}
    used = 0
    for i in sorted((i for i in range(len(bl)) if scores[i] > 0), key=lambda i: -scores[i]):
        if used + size[i] <= budget:
            picked[i], used = scores[i], used + size[i]
        elif not picked:                                  # the best one alone is too long: its start
            a, b, h = bl[i]
            end, room = a, budget
            while end < b and room - (len(lines[end]) + 6) >= 0:
                room -= len(lines[end]) + 6
                end += 1
            return [(a, max(end, a + 1), h, scores[i])]
    for i in sorted(picked, key=lambda i: -picked[i]):    # context: the passage after each, while it fits
        j = i + 1
        if j < len(bl) and j not in picked and used + size[j] <= budget:
            picked[j], used = picked[i] * 0.5, used + size[j]
    out: list[list[Any]] = []
    for i in sorted(picked):
        a, b, h = bl[i]
        if out and out[-1][4] == i - 1:                    # the block before it is in: one excerpt
            out[-1][1], out[-1][3], out[-1][4] = b, max(out[-1][3], picked[i]), i
        else:
            out.append([a, b, h, picked[i], i])
    return [(a, b, h, s) for a, b, h, s, _ in sorted(out, key=lambda x: -x[3])]


def summary(lines: list[str], start: int, description: str | None) -> str:
    """One line about the page: its description, else its first paragraph of prose."""
    if description and description.strip():
        s = description
    else:
        s = ""
        code = screen_mod.code_lines(lines)
        for a, b in screen_mod.passages("\n".join(lines)):
            t = " ".join(x.strip() for x in lines[a:b])
            if a >= start and a not in code and not t.startswith(("#", "|", "-", "*", ">", "!", "[")) and len(t.split()) >= 12:
                s = t
                break
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= SUMMARY_CHARS else s[: SUMMARY_CHARS - 1].rsplit(" ", 1)[0] + "…"


def numbered(lines: list[str], a: int, b: int) -> str:
    """Lines a..b-1 with their 1-based numbers (`  120| …`); blank lines left out."""
    w = len(str(b))
    return "\n".join(f"{i + 1:>{w}}| {lines[i]}" for i in range(a, b) if lines[i].strip())


def cite_line(final_url: str, line: int) -> str:
    """How to cite the page: as a link, and a passage by its line (`#n` is the output's ref; the agent fills it in)."""
    url = quote(final_url, safe=":/?#[]@!$&'*+,;=%~-._")
    host = (urlsplit(final_url).hostname or "the page").removeprefix("www.")
    return f"Cite this page as [{host}]({url}); cite a passage by its line as #n:{line} (the numbers on the left)."


# ---- the result -----------------------------------------------------------------------------

async def shape(hub: Hub, c: Any, client: httpx.AsyncClient | None = None) -> None:
    """web_fetch's result (`c.result`), for the model: numbered, the relevant passages of a long page first, screened."""
    from utils.tools.calls import unwrap, untrusted

    res = c.result
    if not isinstance(res, dict) or not isinstance(res.get("content"), str):
        return
    t0 = time.perf_counter()
    src, raw = unwrap(res["content"])
    wrap = (lambda t: untrusted(src, t)) if src is not None else (lambda t: t)
    args = getattr(c, "arguments", None)
    args = args if isinstance(args, dict) else {}
    origin, outputs = getattr(c, "origin", None) or {}, getattr(c, "outputs", None) or []
    budget = args.get("max_chars") if isinstance(args.get("max_chars"), int) else DEFAULT_MAX
    query = str(args.get("focus") or "").strip() or question_for(origin) or ""
    how = backend(hub) if res.get("truncated") and query and budget > 0 else "off"
    full = None
    if how != "off" and outputs and res.get("kind", "text") == "text":
        try:
            full = (await hub.outputs.text(outputs[0]["output_id"])).text
        except Exception:  # noqa: BLE001: the page's start, as fetched
            full = None
    picks: list[tuple[int, int, str, float]] = []
    by = ""
    if full:
        lines = full.split("\n")
        start = body_start(lines)
        bl = blocks(lines, start)
        scores, by = await rank(hub, query, lines, bl, how, client)
        picks = choose(bl, scores, lines, budget)
    if picks:
        keep = set()
        for a, b, _, _ in picks:
            keep.update(range(a, b))
        sparse = "\n".join(x if i in keep else "" for i, x in enumerate(lines))
        s = await screen_mod.screen_for(hub.config, sparse, "page")
        shown = (s.text if s is not None else sparse).split("\n")
        about = _plain(summary(lines, start, screen_mod.HIDDEN_CHARS.sub("", _unwrapped(res.get("description")))))
        parts = [f"About this page: {about}"] if about else []
        for a, b, h, _ in picks:
            under = f' · under "{_one_line(h)}"' if h else ""
            parts.append(f"── lines {a + 1}–{b} of {len(lines)}{under} ──\n{numbered(shown, a, b)}")
        res["content"] = wrap("\n\n".join(parts))
        res["relevance"] = {
            "by": by, "passages": len(picks), "chars": sum(len(x) for i, x in enumerate(lines) if i in keep),
            "of_chars": len(full), "ms": round((time.perf_counter() - t0) * 1000, 1),
            "note": (f"This page is longer than max_chars, so these are its {len(picks)} part(s) most relevant to "
                     f"{'your focus' if args.get('focus') else 'the question'}, most relevant first, with the saved page's "
                     "line numbers. Read more with hub_read_document or hub_search_document (the output's ref).")}
        first = picks[0][0] + 1
    else:
        s = await screen_mod.screen_for(hub.config, raw, "page")
        text = s.text if s is not None else raw
        tl = text.split("\n")
        res["content"] = wrap(numbered(tl, 0, len(tl))) if raw.strip() else res["content"]
        start = body_start(tl)
        first = next((i + 1 for i in range(start, len(tl)) if tl[i].strip()), 1)
    if s is not None:
        res["screening"] = screen_mod.report(s)
    final = res.get("final_url") or res.get("url") or args.get("url")
    if isinstance(final, str) and final.startswith(("http://", "https://")) and res.get("kind", "text") == "text":
        res["cite"] = cite_line(final, first)


def _unwrapped(v: Any) -> str:
    from utils.tools.calls import unwrap

    return unwrap(v)[1] if isinstance(v, str) else ""


def _plain(s: str) -> str:
    """The about line isn't screened by the model: anything the patterns would remove or doubt drops it."""
    if not s or screen_mod.SUSPECT.search(s) or any(rx.search(s) for rx, _ in screen_mod.HARD):
        return ""
    return s


def _one_line(s: str, cap: int = 80) -> str:
    s = re.sub(r"\s+", " ", s).replace('"', "'").strip()
    return s if len(s) <= cap else s[: cap - 1] + "…"
