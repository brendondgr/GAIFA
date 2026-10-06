"""Scoring a suggested workflow.toml against a hand-written expectation (plans 11.6 and 11.12)."""

from __future__ import annotations

import tomllib
from pathlib import Path


def load_expected(path: Path) -> dict:
    return tomllib.loads(path.read_text())


def score(manifest: dict, expected: dict) -> dict:
    """right: wanted inputs found at the right field; wrong: found under that name but elsewhere,
    or the right field under another name; missed: wanted (or known-missed) and not found;
    extra: found but neither wanted nor maybe."""
    got = {k: f"{v['node']}.{v['field']}" for k, v in manifest.get("inputs", {}).items()}
    want, maybe, known = expected.get("want", {}), expected.get("maybe", {}), expected.get("missed", {})
    right = [k for k, t in want.items() if got.get(k) == t]
    wrong = [k for k, t in want.items() if k in got and got[k] != t]
    wrong += [k for k, t in got.items() if k not in want and t in want.values()]
    wrong += [k for k, t in maybe.items() if k in got and got[k] != t]
    recovered = [k for k, t in known.items() if got.get(k) == t]     # a recorded miss that is now found
    right += recovered
    missed = [k for k in want if k not in got] + [k for k, t in known.items() if t not in got.values()]
    extra = [k for k in got if k not in want and k not in maybe and k not in recovered and got[k] not in want.values()]
    outs = sorted(v["node"] for v in manifest.get("outputs", {}).values())
    return {"right": right, "wrong": wrong, "missed": missed, "extra": extra,
            "task_ok": manifest.get("task") == expected.get("task"),
            "outputs_ok": outs == sorted(expected.get("outputs", outs))}


def line(name: str, s: dict) -> str:
    return (f"{name:26} right {len(s['right']):2}  wrong {len(s['wrong'])}  missed {len(s['missed'])}  extra {len(s['extra'])}"
            f"  task {'ok' if s['task_ok'] else 'WRONG'}  outputs {'ok' if s['outputs_ok'] else 'WRONG'}"
            + (f"  missed: {', '.join(s['missed'])}" if s["missed"] else ""))
