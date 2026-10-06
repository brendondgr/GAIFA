"""Turn catalog entries + overrides into llama-server command lines.

Two shapes: ``single`` runs one model with ``--model``; ``router`` runs
llama-server's router mode over a rendered ``--models-preset`` INI, loading
models on demand (at most ``--models-max`` at once).

Boolean params need care because llama-server has three flag styles:
``--flag [on|off]`` (ON_OFF), switch pairs ``--flag/--no-flag`` (NEGATABLE),
and plain switches. A ``false`` for a plain switch is simply omitted.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from lcpp.catalog import Catalog, ModelEntry
from lcpp.paths import Paths
from lcpp.settings import HOST

ON_OFF = {"flash-attn", "log-colors", "reasoning"}
NEGATABLE = {
    "jinja", "mmap", "slots", "warmup", "cont-batching", "kv-offload", "context-shift",
    "cache-prompt", "webui", "kv-unified", "op-offload", "repack", "cache-idle-slots",
    "log-prefix", "log-timestamps", "models-autoload", "prefill-assistant",
}
PATH_PARAMS = {"mmproj", "model-draft"}
# lcpp owns these; a param with one of these names would fight the supervisor.
RESERVED = {"host", "port", "model", "m", "alias", "a", "models-preset", "models-max", "models-dir"}


def norm_key(key: str) -> str:
    return str(key).removeprefix("--").replace("_", "-")


def flag_args(params: dict[str, Any]) -> list[str]:
    args: list[str] = []
    for raw_key, value in params.items():
        key = norm_key(raw_key)
        if key in RESERVED or value is None or value == "":
            continue
        flag = f"--{key}"
        if isinstance(value, bool):
            if key in ON_OFF:
                args += [flag, "on" if value else "off"]
            elif value:
                args.append(flag)
            elif key in NEGATABLE:
                args.append(f"--no-{key}")
            continue
        if isinstance(value, list):
            for item in value:
                args += [flag, str(item)]
            continue
        args += [flag, str(value)]
    return args


def reserved_keys(params: dict[str, Any]) -> list[str]:
    return [k for k in params if norm_key(k) in RESERVED]


def _resolve_paths(paths: Paths, params: dict[str, Any]) -> dict[str, Any]:
    out = dict(params)
    for key in list(out):
        if norm_key(key) in PATH_PARAMS and out[key]:
            out[key] = str(paths.resolve(out[key]))
    return out


def binary_path(paths: Paths, settings: dict[str, Any]) -> Path:
    return paths.resolve(settings["llama"]["binary"])


def single_params(catalog: Catalog, settings: dict[str, Any], entry: ModelEntry,
                  overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """Server-wide params, then model defaults/overrides, then per-launch overrides."""
    return {**settings["llama"]["server_params"], **catalog.effective(entry, overrides)}


def single_argv(paths: Paths, settings: dict[str, Any], catalog: Catalog, entry: ModelEntry,
                port: int, overrides: dict[str, Any] | None = None) -> list[str]:
    params = _resolve_paths(paths, single_params(catalog, settings, entry, overrides))
    main = paths.resolve(entry.path)
    return [
        str(binary_path(paths, settings)), "--host", HOST, "--port", str(port),
        "--model", str(main), "--alias", ",".join(entry.names),
        *flag_args(params),
    ]


def ini_value(value: Any) -> str:
    if isinstance(value, bool):
        return "on" if value else "off"
    return str(value)


def render_preset(paths: Paths, catalog: Catalog, entries: list[ModelEntry],
                  overrides: dict[str, Any] | None = None) -> str:
    lines = ["version = 1", ""]
    for entry in entries:
        params = _resolve_paths(paths, catalog.effective(entry, overrides))
        lines.append(f"[{entry.id}]")
        lines.append(f"model = {paths.resolve(entry.path)}")
        for key, value in params.items():
            key = norm_key(key)
            if key in RESERVED or value is None or value == "":
                continue
            lines.append(f"{key} = {ini_value(value)}")
        lines.append("")
    return "\n".join(lines)


def router_argv(paths: Paths, settings: dict[str, Any], preset: Path, port: int,
                models_max: int) -> list[str]:
    return [
        str(binary_path(paths, settings)), "--host", HOST, "--port", str(port),
        "--models-preset", str(preset), "--models-max", str(models_max),
        *flag_args(settings["llama"]["server_params"]),
    ]

