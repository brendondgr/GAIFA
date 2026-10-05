import os
import subprocess
import sys
from pathlib import Path

import pytest

from utils import cli

REPO = Path(__file__).resolve().parents[3]
AIHUB = REPO / "bin" / "aihub"


def run(*args, env=None, timeout=30):
    return subprocess.run([str(AIHUB), *args], capture_output=True, text=True, timeout=timeout,
                          env={**os.environ, **(env or {})})


def test_cli_imports_only_the_standard_library():
    code = (
        "import sys, runpy; sys.argv=['aihub','--help']\n"
        "try: runpy.run_path(%r, run_name='__main__')\n"
        "except SystemExit: pass\n"
        "bad = sorted({m.split('.')[0] for m in sys.modules} & {'fastapi','pydantic','httpx','uvicorn','starlette','tomlkit','utils'})\n"
        "print('BAD', bad)" % str(REPO / "utils/cli.py")
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True).stdout
    assert out.strip().endswith("BAD []")


def test_unit_template_renders():
    unit = cli.render_unit(Path("/x/AIHub"))
    assert "@ROOT@" not in unit
    assert "ExecStart=/x/AIHub/.venv/bin/python /x/AIHub/app.py" in unit
    assert "WorkingDirectory=/x/AIHub" in unit and "WantedBy=default.target" in unit


def test_hub_down_says_so(tmp_path):
    r = run("status", env={"AIHUB_URL": "http://127.0.0.1:9", "XDG_CONFIG_HOME": str(tmp_path)})
    assert r.returncode == 1
    assert "AIHub is not running at http://127.0.0.1:9" in r.stdout
    assert "aihub start" in r.stdout
    r = run("load", "tts", env={"AIHUB_URL": "http://127.0.0.1:9"})
    assert r.returncode == 1 and "aihub start" in r.stderr


def test_url_uses_config_port(tmp_path, monkeypatch):
    monkeypatch.delenv("AIHUB_URL")  # without it, the CLI reads the port from config.toml
    (tmp_path / "config.toml").write_text("[hub]\nport = 7444\n")
    r = run("url", "settings", env={"AIHUB_ROOT": str(tmp_path)})
    assert r.stdout.strip() == "http://127.0.0.1:7444/settings"


def test_models_needs_a_running_hub():
    r = run("models", "list")
    assert r.returncode == 1 and "AIHub is not running" in r.stderr


def test_human_formatting():
    assert cli.human_bytes(512) == "512 B"
    assert cli.human_bytes(3 * 1000**3) == "3.0 GB" and cli.human_bytes(999) == "999 B" and cli.human_bytes(1500) == "1.5 KB"
    assert cli.human_secs(59) == "59s" and cli.human_secs(3700) == "1h 1m" and cli.human_secs(90000) == "1d 1h"


def test_status_against_a_running_hub(hub_process, tmp_path):
    live_hub = hub_process.url
    r = run("status", env={"AIHUB_URL": live_hub, "XDG_CONFIG_HOME": str(tmp_path)})
    assert r.returncode == 0, r.stderr
    assert r.stdout.startswith("AIHub 0.1.0 at " + live_hub)
    assert "not installed" in r.stdout and "mods: none (add one with `aihub new <id>`)" in r.stdout


def test_unknown_mod(hub_process):
    r = run("start", "tts", env={"AIHUB_URL": hub_process.url})
    assert r.returncode == 1 and "no mod named 'tts'" in r.stderr and "(service_not_found)" in r.stderr


@pytest.fixture
def mod_root(root, services_dir):
    from utils.tests.conftest import free_port

    services_dir("fake-ok", "fake-crash")
    (root / "config.toml").write_text(
        f"[services.fake-ok]\nport = {free_port()}\nautostart = false\n"
        f'[services.fake-crash]\nport = {free_port()}\nautostart = false\nenv = {{ FAKE_CRASH_S = "0.2" }}\n'
    )
    return root


def test_start_stop_status_with_a_mod(mod_root, hub_process):
    env = {"AIHUB_URL": hub_process.url}
    r = run("start", "fake-ok", env=env)
    assert (r.returncode, r.stdout) == (0, "fake-ok: ready\n"), r.stderr
    r = run("status", env=env)
    assert r.returncode == 0
    row = next(line for line in r.stdout.splitlines() if line.startswith("fake-ok"))
    assert row.split()[:3] == ["fake-ok", "ready", "n/a"]
    r = run("restart", "fake-ok", env=env)
    assert r.stdout == "fake-ok: ready\n"
    r = run("stop", "fake-ok", env=env)
    assert (r.returncode, r.stdout) == (0, "fake-ok: stopped\n")


def test_start_reports_a_failure(mod_root, hub_process):
    r = run("start", "fake-crash", env={"AIHUB_URL": hub_process.url})
    # It exits 0.2 s after launch, before its first health check succeeds.
    assert (r.returncode, r.stdout) == (1, "fake-crash: failed\n")
    assert "exited with status 1 while starting" in r.stderr and "Last log lines:" in r.stderr
