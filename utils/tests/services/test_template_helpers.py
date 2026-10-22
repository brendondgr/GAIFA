"""38.4: the template's PyTorch helpers: device.py (AIHUB_DEVICE, then what torch reaches) and torch_index.py
(the wheel index per accel), and the installer's --accel."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

TPL = Path(__file__).resolve().parents[3] / "services" / "_template"


def load(name: str):
    spec = importlib.util.spec_from_file_location(f"tpl_{name}", TPL / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


dev, idx = load("device"), load("torch_index")


def test_device(monkeypatch):
    monkeypatch.setenv("AIHUB_DEVICE", "xpu")
    assert dev.device() == "xpu" and dev.device("cpu") == "cpu" and dev.device("auto") == "xpu"
    monkeypatch.delenv("AIHUB_DEVICE")
    monkeypatch.setattr(dev, "available", lambda name: name in ("mps", "cpu"))
    assert dev.device() == "mps"
    monkeypatch.setattr(dev, "available", lambda name: name == "cpu")
    assert dev.device() == "cpu"


def test_index_per_accel(monkeypatch):
    assert idx.index("cuda", cuda="12.8") == "https://download.pytorch.org/whl/cu128"
    assert idx.index("cuda", cuda="13.0") == "https://download.pytorch.org/whl/cu130"
    assert idx.index("cuda", cuda="12.2") == "https://download.pytorch.org/whl/cu126"     # too old: the oldest build, and setup says so
    assert idx.index("rocm", gfx="gfx1151") == "https://rocm.nightlies.amd.com/v2/gfx1151/"
    assert idx.index("rocm", gfx="gfx1100") == "https://rocm.nightlies.amd.com/v2/gfx110X-all/"
    assert idx.index("xpu") == "https://download.pytorch.org/whl/xpu"
    assert idx.index("mps", darwin=True) == "https://pypi.org/simple" and idx.index("cpu", darwin=True) == "https://pypi.org/simple"
    assert idx.index("cpu", darwin=False) == idx.index("vulkan", darwin=False) == "https://download.pytorch.org/whl/cpu"
    with pytest.raises(SystemExit):
        idx.index("rocm", gfx="gfx803")


def test_index_from_a_shell():
    r = subprocess.run([sys.executable, str(TPL / "torch_index.py"), "xpu"], capture_output=True, text=True)
    assert r.stdout.strip() == "https://download.pytorch.org/whl/xpu"


def test_install_sh_takes_accel():
    text = (TPL / "install.sh").read_text()
    assert "--accel) ACCEL=" in text and "requirements-torch.txt" in text
    r = subprocess.run(["bash", str(TPL / "install.sh"), "--nope"], capture_output=True, text=True)
    assert r.returncode == 2 and "unknown option --nope" in r.stderr
