"""Profiles: parsing, problems, the seed profiles and the podman line (plan 18.1)."""

from pathlib import Path

import pytest

from vllm_mod.profiles import LABEL, Profile, engine_command, load_profiles, serve_args, utilization
from vllm_mod.settings import Settings

SEEDS = Path(__file__).resolve().parent.parent / "profiles"
GTT = 130_446_385_152          # this machine's mem_info_gtt_total


def _p(**kw) -> Profile:
    return Profile(**{"id": "t", "name": "T", "model": "org/m", "memory_gb": 12, "max_model_len": 8192, **kw})


def test_seed_profiles_parse(tmp_path):
    for f in SEEDS.glob("*.toml"):               # a copy: this machine may park some (profiles/.parked.json)
        (tmp_path / f.name).write_text(f.read_text())
    found, problems = load_profiles(tmp_path)
    assert problems == {}
    assert {"qwen3-0.6b", "qwen3.6-35b-a3b-awq"} <= set(found)
    awq = found["qwen3.6-35b-a3b-awq"]
    assert awq.enforce_eager and awq.trust_remote_code and awq.tool_parser == "qwen3_coder"


def test_parked_profiles_are_skipped(tmp_path):
    for name in ("a", "b"):
        (tmp_path / f"{name}.toml").write_text('name="A"\nmodel="o/m"\nmemory_gb=4\nmax_model_len=4096\n')
    (tmp_path / ".parked.json").write_text('["b"]')
    found, problems = load_profiles(tmp_path)
    assert set(found) == {"a"} and problems == {}
    (tmp_path / ".parked.json").write_text("not json")
    assert set(load_profiles(tmp_path)[0]) == {"a", "b"}          # a broken file parks nothing


def test_problems_are_reported_per_file(tmp_path):
    (tmp_path / "ok.toml").write_text('name="A"\nmodel="o/m"\nmemory_gb=4\nmax_model_len=4096\n')
    (tmp_path / "typo.toml").write_text('name="A"\nmodel="o/m"\nmemory_gb=4\nmax_model_len=4096\nmax_len=1\n')
    (tmp_path / "bad.toml").write_text('name = \n')
    (tmp_path / "Wrong-Case.toml").write_text('name="A"\nmodel="o/m"\nmemory_gb=4\nmax_model_len=4096\n')
    (tmp_path / "other.toml").write_text('id="x"\nname="A"\nmodel="o/m"\nmemory_gb=4\nmax_model_len=4096\n')
    found, problems = load_profiles(tmp_path)
    assert list(found) == ["ok"]
    assert "max_len" in problems["typo.toml"]
    assert set(problems) == {"typo.toml", "bad.toml", "Wrong-Case.toml", "other.toml"}


def test_utilization_is_memory_over_gtt():
    assert utilization(_p(memory_gb=12), GTT) == round(12e9 / GTT, 4)
    with pytest.raises(ValueError, match="more than 95%"):
        utilization(_p(memory_gb=125), GTT)


def test_serve_args_carry_the_profile_flags():
    a = serve_args(_p(enforce_eager=True, trust_remote_code=True, tool_parser="qwen3_coder",
                      reasoning_parser="qwen3", served_name="q", extra_args=["--seed", "1"]), 7801, GTT)
    assert a[:3] == ["vllm", "serve", "org/m"]
    assert a[a.index("--host") + 1] == "127.0.0.1" and a[a.index("--port") + 1] == "7801"
    assert a[a.index("--served-model-name") + 1] == "q"
    assert {"--enforce-eager", "--trust-remote-code", "--enable-auto-tool-choice"} <= set(a)
    assert a[a.index("--tool-call-parser") + 1] == "qwen3_coder"
    assert a[a.index("--reasoning-parser") + 1] == "qwen3"
    assert a[-2:] == ["--seed", "1"]
    b = serve_args(_p(attention_backend=""), 7801, GTT)
    assert "--attention-backend" not in b and "--enable-auto-tool-choice" not in b
    assert b[b.index("--served-model-name") + 1] == "org/m"


def test_engine_command(tmp_path):
    s = Settings(state_dir=tmp_path / "state", hf_home=tmp_path / "hf", image="img@sha256:abc", engine_port=7801)
    cmd = engine_command(_p(env={"X": "1"}), s, GTT)
    assert cmd[:3] == ["podman", "run", "-d"]
    assert cmd[cmd.index("--name") + 1] == "aihub-vllm-t"
    assert LABEL in cmd and "aihub.profile=t" in cmd
    assert cmd[cmd.index("--network") + 1] == "host"
    assert "-p" not in cmd and "--publish" not in cmd
    assert f"{tmp_path / 'hf'}:{tmp_path / 'hf'}" in cmd
    assert f"{tmp_path / 'state' / 'cache'}:{tmp_path / 'state' / 'cache'}" in cmd
    envs = [cmd[i + 1] for i, x in enumerate(cmd) if x == "-e"]
    assert "HF_HUB_OFFLINE=1" in envs and "X=1" in envs and "VLLM_ROCM_USE_AITER=0" in envs
    i = cmd.index("img@sha256:abc")
    assert cmd[i + 1:i + 3] == ["vllm", "serve"]


def test_profile_routes(settings, make_engine, make_downloads):
    from fastapi.testclient import TestClient

    from vllm_mod.server import create_app

    eng = make_engine()
    (settings.profiles_dir / "small.toml").write_text("# keep me\n" + (settings.profiles_dir / "small.toml").read_text())
    with TestClient(create_app(settings, engine=eng, downloads=make_downloads(eng))) as c:
        sch = c.get("/v1/profiles/schema").json()
        assert "id" not in sch["properties"] and "memory_gb" in sch["required"]
        new = {"name": "New", "model": "org/new", "memory_gb": 8, "max_model_len": 2048, "tool_parser": ""}
        r = c.put("/v1/profiles/new-one", json=new)
        assert r.status_code == 200 and r.json()["profile"]["id"] == "new-one"
        text = (settings.profiles_dir / "new-one.toml").read_text()
        assert 'model = "org/new"' in text and "tool_parser" not in text
        assert c.put("/v1/profiles/Bad Id", json=new).json()["code"] == "invalid_id"
        r = c.put("/v1/profiles/x", json={**new, "memory_gb": -1})
        assert r.status_code == 422 and "memory_gb" in r.json()["detail"]
        row = next(p for p in c.get("/v1/profiles").json()["profiles"] if p["id"] == "small")
        body = {k: v for k, v in row.items() if k not in ("downloaded", "local_bytes", "download")}
        r = c.put("/v1/profiles/small", json={**body, "max_model_len": 1024, "alias": None})
        text = (settings.profiles_dir / "small.toml").read_text()
        assert text.startswith("# keep me") and "max_model_len = 1024" in text and "alias" not in text
        assert c.post("/v1/load", json={"profile": "small"}).status_code == 200
        r = c.put("/v1/profiles/small", json={**body, "max_model_len": 2048})
        assert r.json()["note"] == "it applies at the next load"
        assert c.delete("/v1/profiles/small").json()["code"] == "in_use"
        c.post("/v1/unload")
        assert c.delete("/v1/profiles/small").json() == {"deleted": "small"}
        assert c.delete("/v1/profiles/small").status_code == 404
        assert "small" not in [p["id"] for p in c.get("/v1/profiles").json()["profiles"]]
