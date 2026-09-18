#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "llamacpp.json"
SERVICE_NAME = "llamacpp-router.service"
CONSOLE_COMMANDS = {
    "llamacpp-start": "service-start",
    "llamacpp-stop": "service-stop",
    "llamacpp-restart": "service-restart",
    "llamacpp-status": "service-status",
    "llamacpp-logs": "service-logs",
    "llamacpp-models": "list-models",
}
MODEL_METADATA_KEYS = {"path", "model", "params", "nicknames"}
# Params whose values are filesystem paths and must be resolved to absolute
# paths (relative to ROOT) before being written into the models.ini preset.
PATH_PARAM_KEYS = {"mmproj", "model-draft"}
GGUF_SPLIT_RE = re.compile(r"^(?P<prefix>.*-)(?P<index>\d+)-of-(?P<total>\d+)(?P<suffix>\.gguf)$")


def load_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh) or {}
    if not isinstance(data, dict):
        raise SystemExit(f"{path} must contain a JSON object")
    return data


def resolve_path(value: str | os.PathLike[str]) -> Path:
    raw = Path(os.path.expandvars(os.path.expanduser(str(value))))
    return raw if raw.is_absolute() else ROOT / raw


def ini_value(value: Any) -> str:
    if isinstance(value, bool):
        return "on" if value else "off"
    return str(value)


def normalized_flag(name: str) -> str:
    return "--" + name.replace("_", "-").removeprefix("--")


def params_to_args(params: dict[str, Any]) -> list[str]:
    args: list[str] = []
    for key, value in params.items():
        flag = normalized_flag(str(key))
        if value is None:
            continue
        if isinstance(value, bool):
            if value:
                args.append(flag)
            continue
        if isinstance(value, list):
            for item in value:
                args.extend([flag, str(item)])
            continue
        args.extend([flag, str(value)])
    return args


def server_environment(server: dict[str, Any]) -> dict[str, str]:
    raw = server.get("environment") or server.get("env") or {}
    if not isinstance(raw, dict):
        raise SystemExit("server.environment must be a JSON object")
    return {str(key): str(value) for key, value in raw.items()}


def apply_server_environment(config_path: Path) -> dict[str, str]:
    config = load_config(config_path)
    server = config.get("server") or {}
    if not isinstance(server, dict):
        raise SystemExit("server must be a mapping")
    env = server_environment(server)
    os.environ.update(env)
    return env


def format_command(argv: list[str], env: dict[str, str] | None = None) -> str:
    if not env:
        return " ".join(argv)
    prefix = " ".join(f"{key}={shlex.quote(value)}" for key, value in env.items())
    return f"{prefix} {' '.join(argv)}"


def validate_model_file(model_id: str, model_path: Path) -> None:
    if not model_path.exists():
        raise SystemExit(f"model file does not exist for {model_id}: {model_path}")

    match = GGUF_SPLIT_RE.match(model_path.name)
    if not match:
        return

    split_index = int(match.group("index"))
    split_total = int(match.group("total"))
    if split_index != 1 or split_total <= 1:
        return

    width = len(match.group("index"))
    missing: list[Path] = []
    hints: list[str] = []
    for index in range(1, split_total + 1):
        name = (
            f"{match.group('prefix')}{index:0{width}d}-of-"
            f"{match.group('total')}{match.group('suffix')}"
        )
        split_path = model_path.with_name(name)
        if split_path.exists():
            continue
        missing.append(split_path)
        double_suffix = split_path.with_name(f"{split_path.name}.gguf")
        if double_suffix.exists():
            hints.append(f"found {double_suffix.name}; rename it to {split_path.name}")

    if missing:
        details = "\n".join(f"  - {path}" for path in missing)
        hint_text = "\n" + "\n".join(f"  - {hint}" for hint in hints) if hints else ""
        raise SystemExit(
            f"model {model_id!r} is a split GGUF, but required split files are missing:\n"
            f"{details}{hint_text}"
        )


def render_models_ini(config_path: Path) -> Path:
    config = load_config(config_path)
    server = config.get("server") or {}
    model_defaults = config.get("model_defaults") or {}
    models = config.get("models") or {}
    if not isinstance(server, dict):
        raise SystemExit("server must be a mapping")
    if not isinstance(model_defaults, dict):
        raise SystemExit("model_defaults must be a mapping")
    if not isinstance(models, dict) or not models:
        raise SystemExit("models must be a non-empty mapping")

    preset_path = resolve_path(server.get("preset", "LlamaCPP/generated/models.ini"))
    preset_path.parent.mkdir(parents=True, exist_ok=True)

    lines = ["version = 1", ""]
    for model_id, raw_model in models.items():
        if not isinstance(raw_model, dict):
            raise SystemExit(f"model {model_id!r} must be a mapping")
        model_path_raw = raw_model.get("path") or raw_model.get("model")
        if not model_path_raw:
            raise SystemExit(f"model {model_id!r} needs a path")
        model_path = resolve_path(model_path_raw)
        validate_model_file(str(model_id), model_path)

        params = dict(model_defaults)
        raw_params = raw_model.get("params") or {}
        if not isinstance(raw_params, dict):
            raise SystemExit(f"model {model_id!r} params must be a mapping")
        params.update(raw_params)
        for key, value in raw_model.items():
            if key not in MODEL_METADATA_KEYS:
                params[key] = value

        lines.append(f"[{model_id}]")
        lines.append(f"model = {model_path}")
        for key, value in params.items():
            if value and str(key).replace("_", "-") in PATH_PARAM_KEYS:
                value = resolve_path(value)
            lines.append(f"{key} = {ini_value(value)}")
        lines.append("")

    preset_path.write_text("\n".join(lines), encoding="utf-8")
    return preset_path


def server_args(config_path: Path) -> list[str]:
    config = load_config(config_path)
    server = config.get("server") or {}
    if not isinstance(server, dict):
        raise SystemExit("server must be a mapping")

    binary = resolve_path(server.get("binary", "LlamaCPP/bin/current/llama-server"))
    if not binary.exists():
        raise SystemExit(f"llama-server not found: {binary}")

    preset = render_models_ini(config_path)
    host = str(server.get("host", "0.0.0.0"))
    port = str(server.get("port", 7070))
    models_max = str(server.get("models_max", 1))
    params = server.get("params") or {}
    extra_args = server.get("extra_args") or []
    if not isinstance(params, dict):
        raise SystemExit("server.params must be a JSON object")
    if not isinstance(extra_args, list):
        raise SystemExit("server.extra_args must be a JSON array")

    return [
        str(binary),
        "--host",
        host,
        "--port",
        port,
        "--models-preset",
        str(preset),
        "--models-max",
        models_max,
        *params_to_args(params),
        *map(str, extra_args),
    ]


def install_user_service(config_path: Path) -> Path:
    config = load_config(config_path)
    server = config.get("server") or {}
    if not isinstance(server, dict):
        raise SystemExit("server must be a mapping")
    env = server_environment(server)

    service_dir = Path.home() / ".config/systemd/user"
    service_dir.mkdir(parents=True, exist_ok=True)
    service_path = service_dir / SERVICE_NAME
    python = shutil.which("python") or sys.executable
    env_lines = ["Environment=PYTHONUNBUFFERED=1"]
    env_lines.extend(f"Environment={key}={value}" for key, value in env.items())
    service = f"""[Unit]
Description=llama.cpp Router Server
After=network.target

[Service]
Type=simple
WorkingDirectory={ROOT}
ExecStart={python} {ROOT / "scripts/llamacpp.py"} --config {config_path} run
Restart=always
RestartSec=5
LimitNOFILE=65535
{chr(10).join(env_lines)}

[Install]
WantedBy=default.target
"""
    service_path.write_text(service, encoding="utf-8")
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "enable", SERVICE_NAME], check=True)
    return service_path


def install_console_commands() -> Path:
    bin_dir = Path.home() / ".local/bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    target = ROOT / "scripts/llamacpp.py"
    for name in CONSOLE_COMMANDS:
        link = bin_dir / name
        if link.exists() or link.is_symlink():
            link.unlink()
        link.symlink_to(target)
    return bin_dir


def config_models(config_path: Path) -> dict[str, dict[str, Any]]:
    config = load_config(config_path)
    models = config.get("models") or {}
    if not isinstance(models, dict) or not models:
        raise SystemExit("models must be a non-empty mapping")
    return models


def model_names(raw_model: dict[str, Any], model_id: str) -> list[str]:
    names = [model_id]
    nicknames = raw_model.get("nicknames") or []
    if isinstance(nicknames, str):
        nicknames = [nicknames]
    if isinstance(nicknames, list):
        names.extend(str(name) for name in nicknames)
    return names


def resolve_model(config_path: Path, query: str) -> str:
    query_normalized = query.casefold()
    models = config_models(config_path)
    exact: list[str] = []
    partial: list[str] = []

    for model_id, raw_model in models.items():
        if not isinstance(raw_model, dict):
            continue
        names = model_names(raw_model, model_id)
        if any(query_normalized == name.casefold() for name in names):
            exact.append(model_id)
        elif any(query_normalized in name.casefold() for name in names):
            partial.append(model_id)

    matches = exact or partial
    unique = sorted(set(matches))
    if len(unique) == 1:
        return unique[0]
    if not unique:
        raise SystemExit(f"no model matches {query!r}; run llamacpp-models")
    raise SystemExit(f"model nickname {query!r} is ambiguous: {', '.join(unique)}")


def print_models(config_path: Path) -> None:
    for model_id, raw_model in config_models(config_path).items():
        if not isinstance(raw_model, dict):
            continue
        nicknames = [name for name in model_names(raw_model, model_id) if name != model_id]
        suffix = f" ({', '.join(nicknames)})" if nicknames else ""
        print(f"{model_id}{suffix}")


def server_url(config_path: Path) -> str:
    config = load_config(config_path)
    server = config.get("server") or {}
    host = str(server.get("host", "0.0.0.0"))
    if host in {"0.0.0.0", "::"}:
        host = "localhost"
    return f"http://{host}:{server.get('port', 7070)}"


def wait_for_server(config_path: Path, timeout_seconds: int = 30) -> None:
    url = f"{server_url(config_path)}/v1/models"
    deadline = time.time() + timeout_seconds
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return
        except Exception as exc:  # noqa: BLE001 - keep polling until timeout
            last_error = exc
        time.sleep(0.5)
    raise SystemExit(f"server did not become ready at {url}: {last_error}")


def warm_model(config_path: Path, model_id: str) -> None:
    url = f"{server_url(config_path)}/v1/chat/completions"
    body = json.dumps(
        {
            "model": model_id,
            "messages": [{"role": "user", "content": "Reply with exactly: ok"}],
            "max_tokens": 8,
            "temperature": 0,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"failed to load {model_id}: {details}") from exc
    content = payload.get("choices", [{}])[0].get("message", {}).get("content", "")
    suffix = f": {content.strip()}" if content.strip() else ""
    print(f"loaded {model_id}{suffix}")


def service_file_exists() -> bool:
    return (Path.home() / ".config/systemd/user" / SERVICE_NAME).exists()


def systemctl_user(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["systemctl", "--user", *args], check=check, text=True)


def service_start(config_path: Path, model_query: str | None = None) -> None:
    render_models_ini(config_path)
    if not service_file_exists():
        install_user_service(config_path)
    systemctl_user("start", SERVICE_NAME)
    wait_for_server(config_path)
    if model_query:
        warm_model(config_path, resolve_model(config_path, model_query))
    else:
        print(f"llama.cpp is running at {server_url(config_path)}")


def service_restart(config_path: Path, model_query: str | None = None) -> None:
    render_models_ini(config_path)
    if not service_file_exists():
        install_user_service(config_path)
    systemctl_user("restart", SERVICE_NAME)
    wait_for_server(config_path)
    if model_query:
        warm_model(config_path, resolve_model(config_path, model_query))
    else:
        print(f"llama.cpp restarted at {server_url(config_path)}")


def console_argv() -> list[str]:
    invoked_as = Path(sys.argv[0]).name
    command = CONSOLE_COMMANDS.get(invoked_as)
    if not command:
        return sys.argv[1:]
    return [command, *sys.argv[1:]]


def main() -> int:
    parser = argparse.ArgumentParser(description="JSON-driven llama.cpp router helper")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("render", help="render llama.cpp models.ini from JSON config")
    subparsers.add_parser("print-command", help="print the llama-server command")
    subparsers.add_parser("run", help="render config and exec llama-server")
    subparsers.add_parser("install-user-service", help="install and enable the user systemd service")
    subparsers.add_parser("install-console-commands", help="install llamacpp-* commands in ~/.local/bin")
    subparsers.add_parser("list-models", help="list configured model ids and nicknames")
    start_parser = subparsers.add_parser("service-start", help="start service, optionally loading a model")
    start_parser.add_argument("model", nargs="?")
    restart_parser = subparsers.add_parser("service-restart", help="restart service, optionally loading a model")
    restart_parser.add_argument("model", nargs="?")
    subparsers.add_parser("service-stop", help="stop service")
    subparsers.add_parser("service-status", help="show service status")
    subparsers.add_parser("service-logs", help="follow service logs")
    args = parser.parse_args(console_argv())

    config_path = args.config.resolve()
    if args.command == "render":
        print(render_models_ini(config_path))
        return 0
    if args.command == "print-command":
        config = load_config(config_path)
        server = config.get("server") or {}
        env = server_environment(server if isinstance(server, dict) else {})
        print(format_command(server_args(config_path), env))
        return 0
    if args.command == "run":
        apply_server_environment(config_path)
        cmd = server_args(config_path)
        os.execv(cmd[0], cmd)
    if args.command == "install-user-service":
        print(install_user_service(config_path))
        return 0
    if args.command == "install-console-commands":
        print(install_console_commands())
        return 0
    if args.command == "list-models":
        print_models(config_path)
        return 0
    if args.command == "service-start":
        service_start(config_path, args.model)
        return 0
    if args.command == "service-restart":
        service_restart(config_path, args.model)
        return 0
    if args.command == "service-stop":
        systemctl_user("stop", SERVICE_NAME, check=False)
        print("llama.cpp stopped")
        return 0
    if args.command == "service-status":
        systemctl_user("status", SERVICE_NAME, "--no-pager", check=False)
        return 0
    if args.command == "service-logs":
        subprocess.run(["journalctl", "--user", "-u", SERVICE_NAME, "-f"], check=False)
        return 0
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
