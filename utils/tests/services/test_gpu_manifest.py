"""Plan 31.2: `[gpu]` in service.toml (parsing, the env the client reads) and `aihub check`'s warning."""

from __future__ import annotations

from pathlib import Path

from utils import config
from utils.manifest import discover, launch_spec
from utils.services.check import gpu_check

BASE = """
id = "{id}"
[run]
command = ["/bin/true"]
port = {port}
"""


def mod(tmp_path: Path, extra: str, sid: str = "gpumod"):
    d = tmp_path / "services" / sid
    d.mkdir(parents=True)
    port = 5100 + len(list((tmp_path / "services").iterdir()))
    (d / "service.toml").write_text(BASE.replace("{id}", sid).replace("{port}", str(port)) + extra)
    return next(m for m in discover([tmp_path / "services"]) if m.id == sid)


def test_gpu_table_parses_with_defaults(tmp_path):
    m = mod(tmp_path, '[gpu]\n')
    assert not m.errors and m.manifest.gpu.cls == "job" and m.manifest.gpu.group is None


def test_gpu_class_and_group(tmp_path):
    m = mod(tmp_path, '[gpu]\nclass = "interactive"\ngroup = "llm:8080"\n')
    assert not m.errors and (m.manifest.gpu.cls, m.manifest.gpu.group) == ("interactive", "llm:8080")


def test_bad_gpu_table(tmp_path):
    m = mod(tmp_path, '[gpu]\nclass = "urgent"\n')
    assert m.errors and "class" in m.errors[0]
    m2 = mod(tmp_path, '[gpu]\nkind = "job"\n', sid="other")
    assert m2.errors


def test_no_gpu_table(tmp_path):
    assert mod(tmp_path, "").manifest.gpu is None


def test_the_launch_env_carries_the_defaults(tmp_path):
    m = mod(tmp_path, '[gpu]\nclass = "background"\n')
    cfg = config.Config()
    spec = launch_spec(m, cfg, config.build_paths(cfg, tmp_path), 7000)
    assert spec.env["AIHUB_GPU_CLASS"] == "background" and spec.env["AIHUB_GPU_GROUP"] == "gpumod"
    plain = mod(tmp_path, "", sid="plain")
    assert "AIHUB_GPU_CLASS" not in launch_spec(plain, cfg, config.build_paths(cfg, tmp_path), 7000).env


def test_check_warns_a_memory_mod_without_gpu(tmp_path):
    m = mod(tmp_path, '[memory]\nestimate_gb = 4\n').manifest
    status, text = gpu_check(m, None)
    assert status == "warn" and "[gpu]" in text
    status, text = gpu_check(m, {"loaded": True, "model": {"device": "cuda:0"}})
    assert status == "warn" and "cuda:0" in text
    assert gpu_check(m, {"loaded": True, "device": "cpu"})[0] == "ok"


def test_check_is_quiet_without_memory_and_ok_with_gpu(tmp_path):
    assert gpu_check(mod(tmp_path, "").manifest, None) is None
    ok = gpu_check(mod(tmp_path, '[memory]\n[gpu]\nclass = "job"\n', sid="withgpu").manifest, None)
    assert ok[0] == "ok" and "job" in ok[1]
