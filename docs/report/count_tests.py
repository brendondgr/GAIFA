"""Runs every test suite and records the counts in data/test-counts.json (for the report)."""

from __future__ import annotations

import json
import re
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SUITES = [
    ("Hub (utils/tests; includes the Node UI tests)", ".", ["uv", "run", "pytest", "-q", "-p", "no:cacheprovider"], "uv run pytest"),
    ("Agent (scripted model, stand-in hub)", "services/agent", [".venv/bin/python", "-m", "pytest", "-q"], ".venv/bin/python -m pytest"),
    ("Images & Video (comfy)", "services/comfy", [".venv/bin/python", "-m", "pytest", "-q"], ".venv/bin/python -m pytest"),
    ("LLM Relay", "services/relay/web/backend", ["uv", "run", "--frozen", "pytest", "-q"], "uv run pytest"),
    ("LLM Launcher (lcpp)", "services/lcpp", ["uv", "run", "--frozen", "pytest", "-q"], "uv run pytest"),
    ("Speech (tts)", "services/tts", [".venv/bin/python", "-m", "pytest", "-q"], ".venv/bin/python -m pytest"),
    ("3D Generate (gen3d)", "services/gen3d", [".venv/bin/python", "-m", "pytest", "-q"], ".venv/bin/python -m pytest"),
]


def main() -> None:
    out = []
    for name, cwd, cmd, shown in SUITES:
        t0 = time.time()
        p = subprocess.run(cmd, cwd=ROOT / cwd, capture_output=True, text=True, timeout=1200)
        tail = (p.stdout + p.stderr).strip().splitlines()[-1] if (p.stdout + p.stderr).strip() else ""
        n = {k: int(v) for v, k in re.findall(r"(\d+) (passed|failed|skipped|error)", tail)}
        out.append({"name": name, "command": f"{shown} ({cwd})", "passed": n.get("passed", 0), "failed": n.get("failed", 0),
                    "skipped": n.get("skipped", 0), "result": re.sub(r"\s*=+\s*", "", tail)[:80], "seconds": round(time.time() - t0)})
        print(out[-1], flush=True)
    (ROOT / "docs" / "report" / "data" / "test-counts.json").write_text(json.dumps({"ts": time.time(), "suites": out}, indent=1))


if __name__ == "__main__":
    main()
