"""The running tools (plan 27.6) through the mod's routes, with real podman: workspace_run in the
sandbox and on the host, its levels and refusals, output as untrusted text; workspace_python with
an input from the hub's outputs and files out as outputs."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

import sandbox
import server
from fastapi.testclient import TestClient

from test_sandbox import _image_ok

pytestmark = pytest.mark.podman
if not _image_ok():
    pytest.skip("the sandbox image isn't built", allow_module_level=True)

CSV = b"month,revenue\nJan,120\nFeb,340\nMar,210\n"


class FakeHub(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/api/outputs/0123456789ab":
            body, ct = json.dumps({"id": "0123456789ab", "path": "outputs/uploads/2026-10-20/101010-sales.csv"}).encode(), "application/json"
        elif self.path == "/api/outputs/0123456789ab/file":
            body, ct = CSV, "text/csv"
        else:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def hub():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), FakeHub)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


@pytest.fixture
def wc(tmp_path, aihub, hub):
    app = server.create_app(tmp_path / "state", aihub, aihub / "data" / "models", tmp_path / "outputs", hub)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def proj(wc, repo):
    wc.post("/v1/folders", json={"path": str(repo), "level": "run"})
    return repo


def post(c, route, **body):
    return c.post(route, json=body, headers={"X-AIHub-Origin": json.dumps({"thread": "t1", "turn": 3})})


def test_run_in_the_sandbox(wc, proj):
    r = post(wc, "/v1/run", folder="proj", command="PYTHONPATH=. python -c 'import tests.test_calc as t; t.test_mul(); print(\"mul ok\"); t.test_add()'")
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["exit_code"] == 1 and out["where"] == "sandbox" and not out["network"]
    assert out["stdout"].startswith('<untrusted source="proj: PYTHONPATH=. python') and "mul ok" in out["stdout"]
    assert "AssertionError" in out["stderr"] and out["stderr"].endswith("</untrusted>")
    rec = wc.get(f"/v1/runs/{out['run']}").json()
    assert rec["thread"] == "t1" and rec["turn"] == "3" and rec["folder"] == "proj" and rec["cwd"] == str(proj)
    assert wc.get("/v1/runs", params={"thread": "t1"}).json()["runs"][0]["id"] == out["run"]
    assert wc.get("/v1/recent").json()["items"][0]["kind"] == "run"


def test_exit_codes_cwd_and_timeout(wc, proj):
    assert post(wc, "/v1/run", folder="proj", command="exit 3").json()["exit_code"] == 3
    assert post(wc, "/v1/run", folder="proj", command="pwd", cwd="pkg").json()["stdout"].split("\n")[1] == str(proj / "pkg")
    t = post(wc, "/v1/run", folder="proj", command="sleep 20", timeout_s=1).json()
    assert t["state"] == "timeout" and t["exit_code"] is None


def test_levels_and_refusals(wc, proj):
    r = post(wc, "/v1/run", folder="proj", command="pip download six", network=True)
    assert r.status_code == 403 and r.json()["code"] == "level" and "Run + network" in r.json()["detail"]
    assert post(wc, "/v1/run", folder="proj", command="sudo id").json()["code"] == "sudo"
    assert post(wc, "/v1/run", folder="proj", command="git push origin main").json()["code"] == "level"
    wc.patch("/v1/folders/proj", json={"level": "edit"})
    assert post(wc, "/v1/run", folder="proj", command="ls").json()["code"] == "level"


def test_run_with_network_installs_a_package(wc, proj):
    wc.patch("/v1/folders/proj", json={"level": "run_net"})
    r = post(wc, "/v1/run", folder="proj", command="uv venv -q && uv pip install -q six && .venv/bin/python -c 'import six; print(six.__version__)'",   # plain uv pip: into .venv
             network=True, timeout_s=300).json()
    assert r["exit_code"] == 0 and r["network"], r
    assert (proj / ".venv").is_dir()
    offline = post(wc, "/v1/run", folder="proj", command=".venv/bin/python -c 'import six; print(\"still\", six.__name__)'").json()
    assert offline["exit_code"] == 0 and "still six" in offline["stdout"]


def test_run_on_the_host(wc, proj):
    r = post(wc, "/v1/run", folder="proj", command="echo $HOME; test -d $HOME && echo home-visible", where="host").json()
    assert r["where"] == "host" and r["exit_code"] == 0 and "home-visible" in r["stdout"] and r["network"]


def test_python_writes_outputs(wc, tmp_path):
    code = ("import pandas as pd, matplotlib.pyplot as plt, os\n"
            "df = pd.read_csv(os.path.join(os.environ['AIHUB_INPUTS'], 'sales.csv'))\n"
            "print(df.loc[df.revenue.idxmax(), 'month'])\n"
            "df.plot.bar(x='month', y='revenue'); plt.savefig('chart.png')\n")
    r = post(wc, "/v1/python", code=code, inputs=["output:0123456789ab"])
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["exit_code"] == 0, out.get("stderr")
    assert "Feb" in out["stdout"] and out["inputs"] == ["inputs/sales.csv"]
    assert len(out["files"]) == 1 and out["files"][0].endswith("-chart.png")
    png = Path(out["files"][0])
    assert png.parent.parent == tmp_path / "outputs" and png.read_bytes()[:4] == b"\x89PNG"
    side = json.loads(png.with_name(png.name + ".json").read_text())
    assert side["source"] == "workspace_python" and "savefig" in side["code"]
    assert not list((tmp_path / "state" / "python").iterdir())                    # the work folder is gone


def test_python_without_files_and_bad_inputs(wc):
    r = post(wc, "/v1/python", code="print(6 * 7)").json()
    assert r["stdout"].split("\n")[1] == "42" and r["files"] == [] and "become outputs" in r["note"]
    missing = post(wc, "/v1/python", code="open('inputs/sales.csv').read()").json()
    assert missing["exit_code"] == 1 and "pass the files the code reads in `inputs`" in missing["note"]
    assert post(wc, "/v1/python", code="1", inputs=["output:ffffffffffff"]).json()["code"] == "unknown_output"
    assert post(wc, "/v1/python", code="1", inputs=["not a ref"]).json()["code"] == "bad_input"
    assert post(wc, "/v1/python", code="1", network=True).json()["code"] == "level"
    blocked = post(wc, "/v1/python", code="import urllib.request\nurllib.request.urlopen('https://pypi.org', timeout=5)").json()
    assert blocked["exit_code"] != 0


def test_python_in_a_folder(wc, proj):
    r = post(wc, "/v1/python", folder="proj", code="import os\nprint(os.getcwd())\nopen('made.txt','w').write('x')\nopen(os.path.join(os.environ['AIHUB_OUT'],'o.txt'),'w').write('o')").json()
    assert r["exit_code"] == 0 and r["stdout"].split("\n")[1] == str(proj)
    assert (proj / "made.txt").exists() and len(r["files"]) == 1 and r["files"][0].endswith("-out-o.txt")


def test_limits_preflight_for_python(client):
    assert client.post("/v1/limits", json={"tool": "python", "arguments": {"code": "1"}}).json()["action"] == "command"


def test_missing_image(wc, proj, monkeypatch):
    monkeypatch.setattr(wc.app.state.ctx.sandbox, "image_name", "localhost/aihub-nope:0")
    r = post(wc, "/v1/run", folder="proj", command="ls")
    assert r.status_code == 503 and r.json()["code"] == "sandbox_missing"
