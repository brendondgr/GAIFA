"""Status, stats and jobs (plan 18.5): vLLM's /metrics, the sampler, and the §4.6 shape."""

from __future__ import annotations

import time
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from vllm_mod.metrics import Sampler, parse, summary
from vllm_mod.server import create_app

FIXTURE = Path(__file__).parent / "fixtures" / "metrics-0.31.txt"


def test_summary_of_the_real_metrics():
    """Captured from the pinned image (vLLM 0.31.0+strix) serving Qwen3-0.6B after a few requests."""
    s = summary(FIXTURE.read_text())
    assert s["running"] == 0 and s["waiting"] == 0
    assert s["kv_cache"] is not None and 0 <= s["kv_cache"] <= 1
    assert s["generation_tokens"] and s["generation_tokens"] > 0
    assert s["prompt_tokens"] and s["requests"] and s["requests"] >= 1


def test_parse_sums_label_sets_and_skips_comments():
    m = parse('# HELP x\nvllm:request_success_total{finished_reason="stop"} 3.0\n'
              'vllm:request_success_total{finished_reason="length"} 2.0\nbad line\n')
    assert m == {"vllm:request_success_total": 5.0}


def test_sampler_rate_busy_and_idle():
    s = Sampler(httpx.AsyncClient(), window=10)
    t = time.time()
    s.add({"generation_tokens": 100.0, "running": 0}, t - 8)
    s.add({"generation_tokens": 100.0, "running": 0}, t - 6)
    assert s.tokens_per_s == 0 and s.view()["idle_s"] >= 0
    s.add({"generation_tokens": 500.0, "running": 2}, t - 4)
    s.add({"generation_tokens": 900.0, "running": 1}, t)
    assert s.tokens_per_s == 100.0 and s.busy
    assert s.view()["idle_s"] < 1
    s.add({"generation_tokens": 900.0, "running": 0}, t + 20)     # the window drops old samples
    assert s.tokens_per_s == 0.0 and not s.busy


def _status_problems(body: dict) -> list[str]:
    """The hub's own rules (architecture §4.6), restated: the mod can't import the hub."""
    p = []
    assert set(body) >= {"loaded", "busy", "idle_s", "memory_estimate_gb", "stats", "jobs"}
    if len(body["stats"]) > 4:
        p.append("too many stats")
    for s in body["stats"]:
        if not s.get("label") or not isinstance(s.get("value"), (int, float, str)):
            p.append(f"bad stat {s}")
    for j in body["jobs"]:
        if j["state"] not in ("queued", "running", "done", "failed", "cancelled"):
            p.append(f"bad job state {j}")
        if j["progress"] is not None and not 0 <= j["progress"] <= 1:
            p.append(f"bad progress {j}")
    return p


def test_status_through_a_load(settings, make_engine, make_downloads, fetch):
    fetch.delay = 1.0
    eng = make_engine()
    app = create_app(settings, engine=eng, downloads=make_downloads(eng))
    with TestClient(app) as c:
        st = c.get("/v1/status").json()
        assert st["loaded"] is False and st["memory_estimate_gb"] == 31      # big sorts first, overhead 1
        assert [s["label"] for s in st["stats"]] == ["Model", "Tokens/s", "Requests", "KV cache"]
        assert st["stats"][0]["value"] == "none" and st["jobs"] == [] and not _status_problems(st)
        c.post("/v1/load", params={"wait": "false"}, json={"profile": "small"})
        st = c.get("/v1/status").json()
        labels = [j["label"] for j in st["jobs"]]
        assert any(lb.startswith("Download org/small") for lb in labels), labels
        assert any(lb.startswith("Start Small: ") for lb in labels), labels
        assert not _status_problems(st)
        for _ in range(200):
            if c.get("/v1/engine").json()["state"] == "ready":
                break
            time.sleep(0.05)
        with httpx.Client(base_url=f"http://127.0.0.1:{settings.engine_port}") as h:
            h.post("/v1/chat/completions", json={"model": "small", "messages": [{"role": "user", "content": "hi"}]})
        app.state.sampler.every = 0.05
        time.sleep(0.3)
        st = c.get("/v1/status").json()
        assert st["loaded"] is True and st["memory_estimate_gb"] == 3 and st["idle_s"] is not None
        assert st["stats"][0]["value"] == "small"
        assert {j["state"] for j in st["jobs"]} == {"done"}
        assert not _status_problems(st)
        c.post("/v1/unload")
        assert c.get("/v1/status").json()["loaded"] is False
