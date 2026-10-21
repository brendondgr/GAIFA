#!/usr/bin/env bash
# Downloads the judge's eval sources (manifest.toml) into data/state/judge-bench/ and extracts AgentDojo's tasks.
# Run from anywhere; re-running is safe. Then, from the repo root: uv run python -m services.agent.evals.judge.run …
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../../../.." && pwd)"
B="$ROOT/data/state/judge-bench"
mkdir -p "$B"
uv venv -q --allow-existing --python 3.12 --python-preference only-managed "$B/.venv"
uv pip install -q --python "$B/.venv/bin/python" agentdojo==0.1.35 pandas pyarrow
"$B/.venv/bin/python" -I "$HERE/extract_agentdojo.py" "$B/agentdojo-v1.2.jsonl"
HF_HOME="$ROOT/data/models/hf-cache" "$B/.venv/bin/hf" download deepset/prompt-injections --repo-type dataset \
  --revision 4f61ecb038e9c3fb77e21034b22511b523772cdd --local-dir "$B/deepset-prompt-injections" >/dev/null
"$B/.venv/bin/python" -I - "$B/deepset-prompt-injections/data" "$B/deepset.jsonl" <<'PY'
import json, pathlib, sys
import pandas as pd
with open(sys.argv[2], "w") as f:
    for p in sorted(pathlib.Path(sys.argv[1]).glob("*.parquet")):
        for r in pd.read_parquet(p).itertuples():
            f.write(json.dumps({"split": p.name.split("-")[0], "text": r.text, "label": int(r.label)}) + "\n")
PY
echo "judge bench ready in $B"
