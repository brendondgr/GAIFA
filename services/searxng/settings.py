"""Edits to SearXNG's `settings.yml` (plan 26.3), as ruamel round trips so comments and layout stay.

With `use_default_settings: true` (this machine's file, and the image's suggestion), the file holds
only what differs from SearXNG's defaults, and `engines:` entries are merged with the default
engines by `name`: turning an engine off is an entry `{name, disabled: true}`.
"""

from __future__ import annotations

import io
from typing import Any

from ruamel.yaml import YAML, YAMLError
from ruamel.yaml.comments import CommentedMap, CommentedSeq

SAFE_SEARCH = {0: "off", 1: "moderate", 2: "strict"}


def _yaml() -> YAML:
    y = YAML()
    y.preserve_quotes = True
    y.indent(mapping=2, sequence=4, offset=2)
    y.width = 4096
    return y


class BadSettings(ValueError):
    """settings.yml can't be used as it is (it doesn't parse, or isn't a mapping): says where."""


def _where(mark: Any) -> str:
    return f"line {mark.line + 1}, column {mark.column + 1}" if mark is not None else "an unknown place"


def load(text: str) -> CommentedMap:
    try:
        doc = _yaml().load(text) if text.strip() else None
    except YAMLError as e:
        problem = getattr(e, "problem", None) or str(e).splitlines()[0]
        context = getattr(e, "context", None)
        cmark = getattr(e, "context_mark", None)
        also = f" ({context} at {_where(cmark)})" if context and cmark is not None else ""
        raise BadSettings(f"settings.yml doesn't parse: {problem} at {_where(getattr(e, 'problem_mark', None))}{also}") from None
    if doc is None:
        doc = CommentedMap()
    if not isinstance(doc, dict):
        raise BadSettings(f"settings.yml isn't a mapping (its top level is {'a list' if isinstance(doc, list) else 'a single value'})")
    return doc


def dump(doc: CommentedMap) -> str:
    buf = io.StringIO()
    _yaml().dump(doc, buf)
    return buf.getvalue()


def _table(doc: CommentedMap, key: str) -> CommentedMap:
    if not isinstance(doc.get(key), dict):
        doc[key] = CommentedMap()
    return doc[key]


def _engine(doc: CommentedMap, name: str) -> CommentedMap:
    if not isinstance(doc.get("engines"), list):
        doc["engines"] = CommentedSeq()
    for e in doc["engines"]:
        if isinstance(e, dict) and e.get("name") == name:
            return e
    e = CommentedMap(name=name)
    doc["engines"].append(e)
    return e


def set_engine(doc: CommentedMap, name: str, enabled: bool) -> None:
    _engine(doc, name)["disabled"] = not enabled


def set_engine_timeout(doc: CommentedMap, name: str, seconds: float) -> None:
    _engine(doc, name)["timeout"] = float(seconds)


def set_request_timeout(doc: CommentedMap, seconds: float) -> None:
    _table(doc, "outgoing")["request_timeout"] = float(seconds)


def set_safe_search(doc: CommentedMap, level: int) -> None:
    if level not in SAFE_SEARCH:
        raise ValueError("safe_search is 0 (off), 1 (moderate) or 2 (strict)")
    _table(doc, "search")["safe_search"] = level


def set_default_lang(doc: CommentedMap, lang: str) -> None:
    _table(doc, "search")["default_lang"] = lang


def enable_json(doc: CommentedMap) -> None:
    search = _table(doc, "search")
    formats = search.get("formats")
    if not isinstance(formats, list):
        search["formats"] = formats = CommentedSeq(["html"])
    if "json" not in formats:
        formats.append("json")


def summary(doc: dict[str, Any]) -> dict[str, Any]:
    """What this mod adjusts, as the file says it (None: SearXNG's default)."""
    search = doc.get("search") if isinstance(doc.get("search"), dict) else {}
    outgoing = doc.get("outgoing") if isinstance(doc.get("outgoing"), dict) else {}
    engines = [e for e in doc.get("engines") if isinstance(e, dict) and e.get("name")] if isinstance(doc.get("engines"), list) else []
    formats = search.get("formats")
    return {
        "use_default_settings": bool(doc.get("use_default_settings")),
        "safe_search": search.get("safe_search"),
        "default_lang": search.get("default_lang"),
        "request_timeout": outgoing.get("request_timeout"),
        "formats": list(formats) if isinstance(formats, list) else None,
        "json": isinstance(formats, list) and "json" in formats,
        "engines": {str(e["name"]): {k: e[k] for k in ("disabled", "timeout") if k in e} for e in engines},
    }
