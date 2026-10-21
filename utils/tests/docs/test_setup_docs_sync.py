"""The repository's own setup docs are current (plan 23.6): the mods index in docs/setup/README.md
matches the setup docs, every setup doc parses, and every mod has one. The model inventory is
local (data/state/setup/models/), so it isn't checked here. Fix a failure with `aihub docs`."""

from __future__ import annotations

from pathlib import Path

from utils import setupdocs

REPO = Path(__file__).resolve().parents[3]
STRICT = True


def test_setup_docs_are_current() -> None:
    report = setupdocs.sync(REPO, check=True)
    assert report.problems(strict=STRICT) == [], "run `aihub docs` and commit the result"
