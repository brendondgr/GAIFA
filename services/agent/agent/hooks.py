"""Declarative hooks in the tool loop (plan 22.2): rules the harness carries in `hooks.toml`, which the
learner can add. No code runs: four verbs, checked when a version is made.

    [[hook]]
    verb = "hint_after_error"      # append `text` to the result the model sees when the call fails
    tool = "gen3d_make_3d"         # a tool name, or a glob (comfy_*)
    code = "invalid_arguments"     # optional: only for this error code
    text = "Pass the picture as image; Cube3D takes only text."

    [[hook]]
    verb = "cap"                   # refuse calls past per_turn in one turn
    tool = "hub_search_outputs"
    per_turn = 3
    fix = "Use what you found, or ask the user."

    [[hook]]
    verb = "require_first"         # refuse `tool` until `first` ran in this turn
    tool = "gen3d_make_3d"
    first = "view_output"
    when = "image"                 # optional: only when this argument is given

    [[hook]]
    verb = "trim"                  # cap what a noisy result shows the model
    tool = "hub_list_models"
    max_tokens = 1500
"""

from __future__ import annotations

import fnmatch
from typing import Any

VERBS = {"hint_after_error": {"text"}, "cap": {"per_turn"}, "require_first": {"first"}, "trim": {"max_tokens"}}
OPTIONAL = {"hint_after_error": {"code"}, "cap": {"fix"}, "require_first": {"when", "fix"}, "trim": set()}


def problems(data: dict[str, Any], tools: set[str] | None = None) -> list[str]:
    out = []
    hooks = data.get("hook", [])
    if not isinstance(hooks, list) or set(data) - {"hook"}:
        return ["hooks.toml: only [[hook]] tables"]
    for i, h in enumerate(hooks):
        verb = h.get("verb")
        if verb not in VERBS:
            out.append(f"hook {i + 1}: unknown verb {verb!r} (use {', '.join(VERBS)})")
            continue
        if not isinstance(h.get("tool"), str) or not h["tool"]:
            out.append(f"hook {i + 1}: give tool (a name or a glob)")
        missing = VERBS[verb] - set(h)
        extra = set(h) - VERBS[verb] - OPTIONAL[verb] - {"verb", "tool"}
        if missing:
            out.append(f"hook {i + 1} ({verb}): needs {', '.join(sorted(missing))}")
        if extra:
            out.append(f"hook {i + 1} ({verb}): unknown keys {', '.join(sorted(extra))}")
        for k in ("per_turn", "max_tokens"):
            if k in h and (not isinstance(h[k], int) or h[k] < 1):
                out.append(f"hook {i + 1} ({verb}): {k} must be a positive integer")
        if tools is not None and isinstance(h.get("tool"), str) and not any(fnmatch.fnmatchcase(t, h["tool"]) for t in tools):
            out.append(f"hook {i + 1} ({verb}): no tool matches {h['tool']!r}")
    return out


class Hooks:
    def __init__(self, data: dict[str, Any] | None) -> None:
        self.hooks = [h for h in (data or {}).get("hook", []) if isinstance(h, dict) and h.get("verb") in VERBS]

    def _for(self, verb: str, tool: str) -> list[dict[str, Any]]:
        return [h for h in self.hooks if h["verb"] == verb and fnmatch.fnmatchcase(tool, str(h.get("tool") or ""))]

    def before(self, tool: str, args: dict[str, Any], turn_calls: list[str]) -> dict[str, str] | None:
        """A refusal `{code, detail, fix}` when a hook stops this call, else None."""
        for h in self._for("cap", tool):
            if sum(1 for t in turn_calls if t == tool) >= h["per_turn"]:
                return {"code": "hook_cap", "detail": f"{tool} already ran {h['per_turn']}× this turn",
                        "fix": h.get("fix") or "work with what you have, or ask the user"}
        for h in self._for("require_first", tool):
            if h.get("when") and not args.get(h["when"]):
                continue
            if h["first"] not in turn_calls:
                return {"code": "hook_require_first", "detail": f"call {h['first']} before {tool}",
                        "fix": h.get("fix") or f"call {h['first']} first, then {tool} again"}
        return None

    def after(self, tool: str, status: str, code: str | None) -> tuple[str | None, int | None]:
        """(text to append to the result, a token cap for it)."""
        hints = [h["text"] for h in self._for("hint_after_error", tool) if status == "error" and (not h.get("code") or h["code"] == code)]
        caps = [h["max_tokens"] for h in self._for("trim", tool)]
        return ("\n".join(hints) or None), (min(caps) if caps else None)
