import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
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


def test_url_uses_config_port(tmp_path):
    (tmp_path / "config.toml").write_text("[hub]\nport = 7444\n")
    r = run("url", "settings", env={"AIHUB_ROOT": str(tmp_path)})
    assert r.stdout.strip() == "http://127.0.0.1:7444/settings"


def test_later_commands_name_their_phase():
    r = run("new", "foo")
    assert r.returncode == 2 and "Phase 2.8" in r.stderr
    r = run("models", "scan")
    assert "Phase 3" in r.stderr


def test_human_formatting():
    assert cli.human_bytes(512) == "512 B"
    assert cli.human_bytes(3 * 1024**3) == "3.0 GB"
    assert cli.human_secs(59) == "59s" and cli.human_secs(3700) == "1h 1m" and cli.human_secs(90000) == "1d 1h"


@pytest.fixture
def live_hub(tmp_path):
    with __import__("socket").socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = {**os.environ, "AIHUB_ROOT": str(tmp_path)}
    proc = subprocess.Popen([sys.executable, str(REPO / "app.py"), "--port", str(port)], env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            httpx.get(url + "/api/system", timeout=1)
            break
        except httpx.TransportError:
            time.sleep(0.1)
    yield url
    proc.terminate()
    proc.wait(10)


def test_status_against_a_running_hub(live_hub, tmp_path):
    r = run("status", env={"AIHUB_URL": live_hub, "XDG_CONFIG_HOME": str(tmp_path)})
    assert r.returncode == 0, r.stderr
    assert r.stdout.startswith("AIHub 0.1.0 at " + live_hub)
    assert "not installed" in r.stdout and "mods: none yet" in r.stdout


def test_service_command_before_phase_2(live_hub):
    r = run("start", "tts", env={"AIHUB_URL": live_hub})
    assert r.returncode == 1 and "(not_found)" in r.stderr
