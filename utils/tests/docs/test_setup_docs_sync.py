"""The repository's own setup docs are current (plan 23.6): the mods index in docs/setup/README.md
and the support matrix in docs/platforms.md (plan 40.4) match the setup docs, every setup doc parses, and every mod has one. The model inventory is
local (data/state/setup/models/), so it isn't checked here. Fix a failure with `gaifa docs`."""

from __future__ import annotations

from pathlib import Path

from utils import setupdocs
from utils.setupdocs import render
from utils.setupdocs.block import OSES
from utils.setupdocs.envs import load_envs
from utils.tests.conftest import needs_mods

REPO = Path(__file__).resolve().parents[3]
STRICT = True
pytestmark = needs_mods("relay", "lcpp", "tts", "gen3d")   # the index lists every mod's setup docs


def test_setup_docs_are_current() -> None:
    report = setupdocs.sync(REPO, check=True)
    assert report.problems(strict=STRICT) == [], "run `gaifa docs` and commit the result"


def test_the_matrix_agrees_with_every_variant() -> None:
    """Each setup's row in docs/platforms.md marks an accel ✓ on a system exactly when one of its
    variants runs there and lists that system in `tested`."""
    envs, _ = load_envs(REPO)
    page = (REPO / "docs" / "platforms.md").read_text()
    rows = {line.split("](")[1].split(")")[0]: line for line in page.splitlines() if line.startswith("| `")}
    for v in envs:
        cells = [c.strip() for c in rows[render.link(REPO / "docs" / "platforms.md", v.path)].strip("|").split("|")][2:]
        for o, cell in zip(OSES, cells):
            want = {render.RUNS_ON[var.accel]: "✓" if o in var.tested else "○" for var in v.setup.effective_variants() if o in var.os}
            got = dict(part.rsplit(" ", 1) for part in cell.split(" · ")) if cell != "—" else {}
            assert got == want, f"{v.id} on {o}"
