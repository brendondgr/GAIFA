"""The library's eval cases (plan 28.3): ten long reports attached together, beyond the window, with the answer
in one of them; and a picture found among the outputs by what it shows, not by its name.

The questions avoid the documents' own words ("a pet animal" for a cat), so a keyword search misses what a
search by meaning finds.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .docs import pdf
from .harness import Run, Task

ROOT = Path(__file__).resolve().parents[3]

STATIONS = ["Cape Mora", "Gull Island", "Harrow Point", "Esk Head", "Fenwick Shoal", "Lowther Bank", "Saltcombe",
            "Black Nore", "Tarbet Ness", "Wren Rock"]
SECTIONS = ["the lamp room", "the fog signal", "the stairs", "the supply boat", "the weather log", "the paint schedule",
            "the oil store", "the radio", "the visitors", "the gallery rail", "the lens", "the tide tables",
            "the generator", "the garden", "the boathouse", "the library", "the winter storms", "the rescue drills",
            "the water tanks", "the signal flags", "the cottages", "the landing stage", "the chimneys", "the closing notes"]
ANSWER_DOC, ANSWER_PAGE = 7, 15           # the 7th report (#7), page 15


def station_report(i: int) -> bytes:
    """24 pages of ~1,600 characters (≈ 9,600 tokens); together the ten are ≈ 96,000."""
    name = STATIONS[i - 1]
    pages = []
    for p, topic in enumerate(SECTIONS, 1):
        lines = [f"{name} light station, annual inspection. Section {p}: {topic.capitalize()}"]
        lines += [f"Item {k}: at {name} the inspectors found {topic} in serviceable condition for the season."
                  for k in range(17)]
        if i == ANSWER_DOC and p == ANSWER_PAGE:
            lines[6] = (f"Item 5: the relief keeper keeps a ginger cat called Saffron in the boathouse, fed twice "
                        f"daily from the stores.")
        pages.append("\n".join(lines))
    return pdf(pages)


def ten_reports() -> list[tuple[str, bytes]]:
    return [(f"{STATIONS[i - 1].lower().replace(' ', '-')}-inspection.pdf", station_report(i)) for i in range(1, 11)]


def cites(ref: str, page: int):
    def c(r: Run):
        t = r.text()
        return ref in t and str(page) in t, r.final()[:200]
    return (f"cites {ref} p.{page}", c)


PICTURES = [("IMG_2041", "agent/evals/fixtures/red-car.png"), ("IMG_2042", "agent/evals/fixtures/blue-house.png"),
            ("IMG_2043", "../docs/assets/overview.png"), ("IMG_2044", "relay/docs/assets/Dashboard.png")]
CAR = "IMG_2041"


def seed_pictures():
    """Four pictures in outputs/eval/ with camera-style names, so only what they show can tell them apart.
    Made once (a seed from an earlier day is reused)."""
    def setup() -> None:
        d = ROOT / "outputs" / "eval" / time.strftime("%Y-%m-%d")
        d.mkdir(parents=True, exist_ok=True)
        for title, src in PICTURES:
            if not list((ROOT / "outputs" / "eval").glob(f"*/*-{title.lower()}.png")):
                f = d / f"{time.strftime('%H%M%S')}-{title.lower()}.png"
                f.write_bytes((ROOT / "services" / src).read_bytes())
                f.with_name(f.name + ".json").write_text(json.dumps({"title": f"{title}.png", "kind": "image"}))
    return setup


def _hits(res: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        body = json.loads(res.get("content") or "{}") if isinstance(res.get("content"), str) else (res.get("content") or {})
    except ValueError:
        return []
    if isinstance(body, dict) and isinstance(body.get("result"), dict):     # the hub's {status, result} envelope
        body = body["result"]
    return [h for h in (body.get("results") if isinstance(body, dict) else None) or [] if isinstance(h, dict)]


def found_first(stem: str):
    """A library search ranked the seeded picture first."""
    def c(r: Run):
        firsts = [h[0].get("title") for res in r.results("embed_library_search") if (h := _hits(res))]
        return any(stem in str(t) for t in firsts), f"first hits {firsts[:3]}"
    return (f"the search ranks {stem} first", c)


def points_to(stem: str):
    """The reply names the picture, or the agent showed it (view_output on its ref)."""
    def c(r: Run):
        ids = {h["output"] for res in r.results("embed_library_search") for h in _hits(res) if stem in str(h.get("title"))}
        shown = [str(c.get("arguments", {}).get("ref") or "") for c in r.calls("view_output", by=None)]
        ok = stem in r.text() or any(s in ids for s in shown) or any(i in r.text() for i in ids)
        return ok, r.final()[:160]
    return (f"the answer is {stem}", c)


def _used(name: str):
    return (f"used {name}", lambda r: (bool(r.calls(name, by=None)), ""))


def _mentions(*words: str):
    return (f"reply mentions {'/'.join(words)}", lambda r: (any(w.lower() in r.text().lower() for w in words), r.final()[:160]))


async def _attach_reports(hub: str) -> list[str]:
    """Upload the ten reports (`POST /api/outputs/upload`); their ids ride on the first turn."""
    import httpx

    async with httpx.AsyncClient(base_url=hub, timeout=60, trust_env=False) as c:
        out = []
        for name, data in ten_reports():
            r = await c.post("/api/outputs/upload", params={"name": name}, content=data)
            r.raise_for_status()
            out.append(r.json()["id"])
        return out


TASKS: list[Task] = [
    Task("library_ten_docs", "context",
         ["These are this year's ten light-station inspection reports. Is any pet animal kept at one of the stations? "
          "Which station, what is the animal called, and where in the reports does it say so?"],
         [_mentions("Saffron"), _mentions(STATIONS[ANSWER_DOC - 1]), cites(f"#{ANSWER_DOC}", ANSWER_PAGE)],
         attach=_attach_reports, timeout=900,
         note="plan 28.3: ten 24-page reports (~96k tokens together); the answer is on #7 p.15, worded differently"),
    Task("library_red_car", "context", ["Find the picture of the red car among my outputs."],
         [_used("embed_library_search"), found_first(CAR), points_to(CAR)],
         setup=seed_pictures(), note="plan 28.3: four pictures with camera names; only what they show tells them apart"),
]
