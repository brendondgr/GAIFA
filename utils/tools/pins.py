"""@-mentions on a call (plan 48.3): what the user's message named, filled into that turn's calls.

The agent passes them on the call's origin as `pins`: {"tts_speak": {"name": "Brendon"}, "comfy_generate_image":
{"workflow": "qwen21-turbo-t2i"}}. A pinned field the model left out (or that a default or a preference filled) takes
the pin, marked `filled` = "mention" on the card. One the model set to something else also takes the pin, and the call
asks (a card) even where it would run at once: the user's message and the model disagree, so the user decides.
"""

from __future__ import annotations

from typing import Any


def apply(tool: Any, arguments: Any, origin: dict[str, Any] | None, filled: list[str],
          how: dict[str, str]) -> tuple[Any, list[str], list[str]]:
    """(arguments, filled, fields the model had set otherwise). `how` is updated in place."""
    pins = (origin or {}).get("pins")
    mine = pins.get(tool.name) if isinstance(pins, dict) else None
    if not isinstance(mine, dict) or not isinstance(arguments, dict):
        return arguments, filled, []
    props = (tool.parameters or {}).get("properties") or {}
    out, over = dict(arguments), []
    for k, v in mine.items():
        if k not in props or ("enum" in props[k] and v not in props[k]["enum"]):
            continue                                # not this tool's field, or not one of its choices (an edit pack on generate)
        if k in out and k not in filled and out[k] != v:
            over.append(k)
        out[k] = v
        how[k] = "mention"
        filled = [*[x for x in filled if x != k], k]
    return out, filled, over
