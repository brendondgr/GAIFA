"""The CLI end to end against a real uvicorn daemon (fake llama-server)."""

from __future__ import annotations

import socket
import subprocess
import sys
import threading
import time

import pytest
import uvicorn

from lcpp import cli
from lcpp.backends.subprocess import SubprocessBackend
from lcpp.daemon.app import create_app


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def daemon(fake_home):
    port = free_port()
    app = create_app(fake_home, SubprocessBackend(fake_home.state / "logs"))
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    while not server.started:
        time.sleep(0.02)
    url = f"http://127.0.0.1:{port}"
    yield url
    cli.main(["--daemon", url, "stop", "all", "--wait"])
    server.should_exit = True
    t.join(10)


def lcpp(url, *args, capsys=None):
    code = cli.main(["--daemon", url, *args])
    out = capsys.readouterr() if capsys else None
    return code, out


def test_parser_help_and_spec():
    p = cli.build_parser()
    a = p.parse_args(["start", "minicpm", "-p", "7072", "-c", "8192", "-s", "parallel=2",
                      "-s", "flash-attn=off", "--no-relay"])
    spec = cli.build_spec(a)
    assert spec == {"kind": "single", "model_id": "minicpm", "port": 7072,
                    "params": {"parallel": 2, "flash-attn": False, "ctx-size": 8192},
                    "relay": {"enabled": False, "alias": None}}
    a = p.parse_args(["start", "--router", "--models", "a,b", "--models-max", "2"])
    assert cli.build_spec(a) == {"kind": "router", "params": {}, "model_ids": ["a", "b"], "models_max": 2}


def test_daemon_down_message(capsys):
    code, out = lcpp("http://127.0.0.1:1", "status", capsys=capsys)
    assert code == 1 and "lcpp service start" in out.err


def test_start_status_logs_chat_stop(daemon, capsys):
    code, out = lcpp(daemon, "start", "minicpm", "--port", "17085", "--no-relay", capsys=capsys)
    assert code == 0 and "minicpm5-2b-17085 ready on http://127.0.0.1:17085/v1" in out.out
    code, out = lcpp(daemon, "status", capsys=capsys)
    assert "minicpm5-2b-17085" in out.out and "17085" in out.out
    code, out = lcpp(daemon, "logs", "17085", "-n", "5", capsys=capsys)
    assert "listening" in out.out
    code, out = lcpp(daemon, "chat", "17085", "hi", capsys=capsys)
    assert code == 0 and "Hello from the fake server." in out.out and "tok/s" in out.err
    code, out = lcpp(daemon, "start", "gemma4-19B", "--port", "17085", capsys=capsys)
    assert code == 1 and "in use by lcpp instance" in out.err
    code, out = lcpp(daemon, "stop", "17085", "--wait", capsys=capsys)
    assert code == 0 and "stopped" in out.out


def test_start_failure_shows_cause(daemon, capsys):
    code, out = lcpp(daemon, "start", "broken", capsys=capsys)
    assert code == 1 and "out of device memory" in out.err


def test_dry_run_and_models(daemon, capsys):
    code, out = lcpp(daemon, "start", "gemma4-26B", "--dry-run", capsys=capsys)
    assert code == 0 and "--mmproj" in out.out and "estimated" in out.out
    code, out = lcpp(daemon, "models", capsys=capsys)
    assert "gemma-4-26B-it" in out.out and "vision,speculative" in out.out
    code, out = lcpp(daemon, "models", "--discovered", capsys=capsys)
    assert "fresh-7b" in out.out


def test_cli_import_stays_light():
    """The CLI must not drag in the server stack; it is what makes `lcpp status` instant."""
    code = ("import sys, lcpp.cli, lcpp.doctor; "
            "heavy = [m for m in ('fastapi', 'uvicorn', 'httpx', 'pydantic', 'starlette') if m in sys.modules]; "
            "print(','.join(heavy))")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout
    assert out.strip() == ""
