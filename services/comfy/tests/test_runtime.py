"""39.6: which ComfyUI runtime a machine uses (bin/comfyui runtime) and the native launch command."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

BIN = Path(__file__).resolve().parents[1] / "bin"


def sh(*args: str, **env: str) -> str:
    e = {k: v for k, v in os.environ.items() if not k.startswith(("AIHUB_", "COMFY_"))}
    r = subprocess.run([str(BIN / args[0]), *args[1:]], capture_output=True, text=True, env={**e, **env})
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def test_runtime_per_variant():
    assert sh("comfyui", "runtime") == "toolbox"                                    # nothing recorded: this machine
    assert sh("comfyui", "runtime", AIHUB_ACCEL="rocm", AIHUB_GPU_ARCH="gfx1151") == "toolbox"
    assert sh("comfyui", "runtime", AIHUB_ACCEL="rocm", AIHUB_GPU_ARCH="gfx1100") == "native"
    for accel in ("cuda", "xpu", "mps", "cpu"):
        assert sh("comfyui", "runtime", AIHUB_ACCEL=accel) == "native"
    assert sh("comfyui", "runtime", COMFY_RUNTIME="native") == "native"


def test_native_command():
    cpu = sh("comfyui-native", "command", AIHUB_ACCEL="cpu", COMFY_PORT_UI="8299")
    assert "runtime/venv/bin/python main.py --listen 127.0.0.1 --port 8299" in cpu and cpu.endswith("--enable-manager --preview-method auto --cpu")
    assert not sh("comfyui-native", "command", AIHUB_ACCEL="cuda").endswith("--cpu")
    assert "--disable-mmap" not in cpu and "--fp32-vae" not in cpu           # gfx1151's flags stay with the toolbox


def test_toolbox_only_commands_say_so():
    e = {k: v for k, v in os.environ.items() if not k.startswith(("AIHUB_", "COMFY_"))}
    r = subprocess.run([str(BIN / "comfyui"), "update"], capture_output=True, text=True, env={**e, "AIHUB_ACCEL": "cuda"})
    assert r.returncode == 1 and "runs ComfyUI natively" in r.stdout
