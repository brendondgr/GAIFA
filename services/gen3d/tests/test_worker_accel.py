"""39.7: the worker's command per variant: the ROCm image as before, or the script on the host for CUDA."""

from __future__ import annotations

import dataclasses

from gen3d import worker
from gen3d.config import settings


def variant(monkeypatch, accel: str) -> None:
    monkeypatch.setattr(worker, "settings", dataclasses.replace(settings, accel=accel))   # settings is frozen


def test_rocm_runs_in_the_image(monkeypatch):
    variant(monkeypatch, "rocm")
    w = worker.CubeWorker("cube")
    w.name = "gen3d-worker-cube-1-1"
    cmd = w.command()
    assert not w.native and cmd[:3] == [settings.podman, "run", "--rm"] and "/dev/kfd" in cmd
    assert any(x == "TORCH_ROCM_AOTRITON_ENABLE_EXPERIMENTAL=1" for x in cmd) and settings.image in cmd


def test_cuda_runs_on_the_host(monkeypatch):
    variant(monkeypatch, "cuda")
    w = worker.CubeWorker("sam3do")
    argv, env = w.native_command()
    assert w.native and argv[:2] == ["bash", "-c"] and "sam3do_worker.py" in argv[2] and "/.venv/bin/activate" in argv[2]
    assert "podman" not in " ".join(argv)
    assert not any(k.startswith(("MIOPEN", "TORCH_ROCM", "ROCPROFILER", "PYTORCH_HIP")) for k in env)
    assert env["PYTORCH_CUDA_ALLOC_CONF"] == "expandable_segments:True" and env["LIDRA_SKIP_INIT"] == "true"
    assert env["PYTHONPATH"].split(":")[0].endswith("workers/shims")             # the same shims as in the image


def test_cuda_skips_the_container_cleanup(monkeypatch):
    import asyncio

    variant(monkeypatch, "cuda")
    w = worker.CubeWorker("cube")
    asyncio.run(w._cleanup_stale())                                  # no podman call: nothing to clean on the host
    assert not w._cleaned
