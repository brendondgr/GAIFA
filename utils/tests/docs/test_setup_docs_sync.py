"""The repository's own setup docs match its registry (plan 23.2). Fix a failure with `aihub docs`.
Coverage (an environment and a source for every model, a setup doc for every mod with models)
turns on in 23.6, with `STRICT`."""

from __future__ import annotations

from pathlib import Path

from utils import setupdocs

REPO = Path(__file__).resolve().parents[3]
STRICT = False


def test_setup_docs_are_current() -> None:
    report = setupdocs.sync(REPO, check=True)
    assert report.problems(strict=STRICT) == [], "run `aihub docs` and commit the result"
