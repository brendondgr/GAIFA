"""39.4: scripts/install-runtime.sh per accelerator, as a dry run: gfx1151's locks as before, the engines'
installers with each accel's PyTorch index elsewhere, and Breeze only where it runs."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "install-runtime.sh"


def dry(*args: str, arch: str = "gfx1151") -> list[str]:
    env = {**os.environ, "GAIFA_GPU_ARCH": arch, "PATH": f"/nonexistent:{os.environ['PATH']}"}   # no nvidia-smi: cu126
    env.pop("GAIFA_ACCEL", None)
    r = subprocess.run(["bash", str(SCRIPT), "--dry-run", *args], capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    return [line for line in r.stdout.splitlines() if not line.startswith("==")]


def test_gfx1151_installs_the_locks_as_before():
    out = " ".join(dry("--accept-breeze-license"))
    assert "locks/kokoro.txt" in out and "locks/breeze-tts.txt" in out
    assert "--gpu rocm --rocm-index https://rocm.nightlies.amd.com/v2/gfx1151/" in out and "torch\\[device-gfx1151\\]" in out


def test_cuda():
    out = dry("--accel", "cuda", "--accept-breeze-license")
    assert any("engines/install.sh --gpu cuda --cuda cu" in x for x in out)
    assert any("--backend cuda" in x and "download.pytorch.org/whl/cu" in x and "torch==2.9.1" in x for x in out)
    assert not any("locks/" in x for x in out)


def test_another_amd_gpu_takes_its_family_eager():
    out = " ".join(dry("--accel", "rocm", "--accept-breeze-license", arch="gfx1100"))
    assert "--rocm-arch gfx1100" in out and "v2/gfx110X-all/" in out and "--fast ''" in out and "locks/" not in out


def test_xpu_and_mps_have_no_breeze():
    for accel in ("xpu", "mps"):
        out = dry("--accel", accel, "--accept-breeze-license")
        assert f"engines/install.sh --gpu {accel} --prefix" in out[0]
        assert out[-1] == f"Breeze has no {accel} build (it runs on ROCm, CUDA or the CPU): skipped"


def test_cpu_only_on_purpose():
    out = dry("--accel", "cpu", "--accept-breeze-license")
    assert "--gpu cpu" in out[0] and out[-1].startswith("Breeze on the CPU is many times slower")
    out = dry("--accel", "cpu", "--accept-breeze-license", "--allow-cpu-breeze")
    assert "--backend cpu" in out[-1] and "whisper-base.en" in out[-1] and "download.pytorch.org/whl/cpu" in out[-1]


def test_without_the_licence_breeze_is_skipped():
    assert dry("--accel", "cuda")[-1].startswith("Breeze TTS 2 is research / non-commercial only")
