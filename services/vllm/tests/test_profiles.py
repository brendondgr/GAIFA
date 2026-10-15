"""Profiles: parsing, problems, the seed profiles and the podman line (plan 18.1)."""

from pathlib import Path

import pytest

from vllm_mod.profiles import LABEL, Profile, engine_command, load_profiles, serve_args, utilization
from vllm_mod.settings import Settings

SEEDS = Path(__file__).resolve().parent.parent / "profiles"
GTT = 130_446_385_152          # this machine's mem_info_gtt_total


def _p(**kw) -> Profile:
    return Profile(**{"id": "t", "name": "T", "model": "org/m", "memory_gb": 12, "max_model_len": 8192, **kw})


def test_seed_profiles_parse():
    found, problems = load_profiles(SEEDS)
    assert problems == {}
    assert {"qwen3-0.6b", "qwen3.6-35b-a3b-awq"} <= set(found)
    awq = found["qwen3.6-35b-a3b-awq"]
    assert awq.enforce_eager and awq.trust_remote_code and awq.tool_parser == "qwen3_coder"


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
