"""Eval tasks for the workspace mod (plan 27.6): fix a failing test in a fixture folder (edit + run)
in Accept edits mode, and analyse an attached CSV into a chart output. Both run live (their
settings turn the dry run off): the fixture is a fresh folder in the temp dir, added as a workspace
at Run for the task and removed after."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from .harness import Run, Task

CALC = "def add(a, b):\n    return a - b\n\n\ndef mul(a, b):\n    return a * b\n"
TESTS = ("import unittest\n\nfrom calc import add, mul\n\n\nclass CalcTest(unittest.TestCase):\n"
         "    def test_add(self):\n        self.assertEqual(add(2, 3), 5)\n\n    def test_mul(self):\n        self.assertEqual(mul(2, 3), 6)\n\n\n"
         "if __name__ == \"__main__\":\n    unittest.main()\n")


def sales_csv() -> str:
    """Three years of daily sales (about 50 KB, too big to go into the message whole, so the agent
    must pass it to workspace_python); July 2025 has the most revenue."""
    import datetime
    import random

    rnd = random.Random(27)
    day, rows = datetime.date(2024, 1, 1), ["date,region,orders,revenue"]
    while day <= datetime.date(2026, 12, 31):
        for region in ("north", "south"):
            orders = rnd.randint(20, 60)
            rev = orders * rnd.randint(18, 26) * (3 if (day.year, day.month) == (2025, 7) else 1)
            rows.append(f"{day.isoformat()},{region},{orders},{rev}")
        day += datetime.timedelta(days=1)
    return "\n".join(rows) + "\n"


def fixture_folder(level: str = "run"):
    """A folder with a bug and a failing test, added to the workspace mod (through the hub) at `level`."""
    async def attach(hub: str) -> dict[str, Any]:
        import httpx

        d = Path(tempfile.mkdtemp(prefix="aihub-eval-calc-"))
        (d / "calc.py").write_text(CALC)
        (d / "test_calc.py").write_text(TESTS)
        (d / "README.md").write_text("# calc\n\nRun the tests with `python -m unittest`.\n")
        async with httpx.AsyncClient(base_url=hub, timeout=30, trust_env=False) as c:
            r = await c.post("/api/s/workspace/v1/folders", json={"path": str(d), "level": level, "id": d.name.lower()[:47]})
            r.raise_for_status()
        return {"ids": [], "vars": {"folder": r.json()["id"], "path": str(d)}}
    return attach


async def remove_folder(hub: str, vars_: dict[str, Any]) -> None:
    import httpx

    if vars_.get("folder"):
        async with httpx.AsyncClient(base_url=hub, timeout=30, trust_env=False) as c:
            await c.delete(f"/api/s/workspace/v1/folders/{vars_['folder']}")


def csv_upload():
    async def attach(hub: str) -> list[str]:
        import httpx

        async with httpx.AsyncClient(base_url=hub, timeout=60, trust_env=False) as c:
            r = await c.post("/api/outputs/upload", params={"name": "sales.csv"}, content=sales_csv().encode())
            r.raise_for_status()
            return [r.json()["id"]]
    return attach


def fixed():
    def c(r: Run):
        p = Path((r.extra.get("vars") or {}).get("path", "/nonexistent")) / "calc.py"
        text = p.read_text() if p.exists() else ""
        return "a + b" in text and "a - b" not in text, text.split("\n")[1] if text else "no calc.py"
    return ("calc.add fixed in place", c)


def green_after_edit():
    """A test run after the last edit exited 0 with unittest's OK (workspace_run, or workspace_python running the tests)."""
    def c(r: Run):
        evs = r.events
        last_edit = max((e["seq"] for e in evs if e["type"] == "tool_result" and e["payload"]["name"] in ("workspace_edit", "workspace_write")
                         and e["payload"]["status"] == "done"), default=None)
        if last_edit is None:
            return False, "no edit"
        runs = [e["payload"] for e in evs if e["type"] == "tool_result" and e["payload"]["name"] in ("workspace_run", "workspace_python")
                and e["seq"] > last_edit]
        ok = any('"exit_code": 0' in (p.get("content") or "") and "OK" in (p.get("content") or "") for p in runs)
        return ok, f"{len(runs)} run(s) after the edit"
    return ("tests pass after the edit", c)


def no_card_for_edits():
    def c(r: Run):
        cards = [a for a in r.of("approval") if a.get("tool") in ("workspace_edit", "workspace_write")]
        return not cards, f"{len(cards)} edit card(s)"
    return ("edits applied without a card (Accept edits)", c)


def ran_ok(name: str):
    def c(r: Run):
        got = [x for x in r.results(name) if x["status"] == "done" and '"exit_code": 0' in (x.get("content") or "")]
        return bool(got), f"{len(got)} clean {name} run(s)"
    return (f"{name} ran cleanly", c)


def made_image():
    def c(r: Run):
        got = [o["kind"] for o in r.outputs()]
        return "image" in got, f"outputs {got}"
    return ("made a chart (an image output)", c)


def says(*words: str):
    def c(r: Run):
        t = r.text().lower()
        return any(w.lower() in t for w in words), r.final()[:160]
    return (f"reply mentions {'/'.join(words)}", c)


TASKS = [
    Task("ws_fix_test", "capability",
         ["The tests in the workspace folder `{folder}` fail. Run them (python -m unittest), find the bug, fix it, and run them again."],
         [fixed(), green_after_edit(), no_card_for_edits()],
         mode="accept_edits", settings={"dry_run": False}, attach=fixture_folder("run"), teardown=remove_folder, timeout=900,
         note="plan 27.6: edit + run in Accept edits; the run's card is approved by the harness"),
    Task("ws_csv_chart", "capability",
         ["Make a bar chart of total revenue per month from the attached sales CSV, and tell me which month had the most revenue."],
         [ran_ok("workspace_python"), made_image(), says("July 2025", "2025-07", "Jul 2025", "July of 2025")],
         mode="accept_edits", settings={"dry_run": False}, attach=csv_upload(), timeout=900,
         note="plan 27.6: workspace_python with an attached CSV; the chart becomes an output"),
]
