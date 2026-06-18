#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError as exc:  # pragma: no cover - environment guard
    raise SystemExit("PyYAML is required. Install it with: python -m pip install PyYAML") from exc


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "llamacpp.yaml"
SERVICE_NAME = "llamacpp-router.service"


def load_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise SystemExit(f"{path} must contain a YAML mapping")
    return data


def resolve_path(value: str | os.PathLike[str]) -> Path:
    raw = Path(os.path.expandvars(os.path.expanduser(str(value))))
    return raw if raw.is_absolute() else ROOT / raw


def ini_value(value: Any) -> str:
    if isinstance(value, bool):
        return "on" if value else "off"
    return str(value)


def render_models_ini(config_path: Path) -> Path:
    config = load_config(config_path)
    server = config.get("server") or {}
    models = config.get("models") or {}
    if not isinstance(server, dict):
        raise SystemExit("server must be a mapping")
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
        if not model_path.exists():
            raise SystemExit(f"model file does not exist: {model_path}")

        params = dict(raw_model.get("params") or {})
        for key, value in raw_model.items():
            if key not in {"path", "model", "params"}:
                params[key] = value

        lines.append(f"[{model_id}]")
        lines.append(f"model = {model_path}")
        for key, value in params.items():
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
    port = str(server.get("port", 9090))
    models_max = str(server.get("models_max", 1))
    extra_args = server.get("extra_args") or []
    if not isinstance(extra_args, list):
        raise SystemExit("server.extra_args must be a YAML list")

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
        *map(str, extra_args),
    ]


def install_user_service(config_path: Path) -> Path:
    service_dir = Path.home() / ".config/systemd/user"
    service_dir.mkdir(parents=True, exist_ok=True)
    service_path = service_dir / SERVICE_NAME
    python = shutil.which("python") or sys.executable
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
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=default.target
"""
    service_path.write_text(service, encoding="utf-8")
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "enable", SERVICE_NAME], check=True)
    return service_path


def main() -> int:
    parser = argparse.ArgumentParser(description="YAML-driven llama.cpp router helper")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("render", help="render llama.cpp models.ini from YAML")
    subparsers.add_parser("print-command", help="print the llama-server command")
    subparsers.add_parser("run", help="render config and exec llama-server")
    subparsers.add_parser("install-user-service", help="install and enable the user systemd service")
    args = parser.parse_args()

    config_path = args.config.resolve()
    if args.command == "render":
        print(render_models_ini(config_path))
        return 0
    if args.command == "print-command":
        print(" ".join(server_args(config_path)))
        return 0
    if args.command == "run":
        os.execv(server_args(config_path)[0], server_args(config_path))
    if args.command == "install-user-service":
        print(install_user_service(config_path))
        return 0
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
