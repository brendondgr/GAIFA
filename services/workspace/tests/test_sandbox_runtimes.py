"""39.1: the sandbox's command line per runtime and system: podman on Linux (as before), docker, podman on
macOS; SELinux's label only where it's enforcing."""

from __future__ import annotations

import os
from pathlib import Path

from sandbox import Run, Sandbox


def argv(tmp_path: Path, network: bool = False, **kw) -> list[str]:
    home = tmp_path / "home"
    (home / ".cache" / "uv").mkdir(parents=True)
    sb = Sandbox(tmp_path / "state", home=home, **kw)
    return sb.argv(Run("run_x", "echo hi", "sandbox", str(tmp_path), network=network), tmp_path, [(tmp_path, "rw")], {})


def test_podman_on_linux_as_before(tmp_path):
    a = argv(tmp_path, podman="podman", linux=True, selinux=True)
    assert a[:7] == ["podman", "run", "--rm", "--name", "gaifa-ws-run_x", "--userns=keep-id", "--security-opt"] and "label=disable" in a
    assert "--network=none" in a and any(x.endswith(":O") for x in a)
    assert "--network=pasta" in argv(tmp_path / "n", network=True, podman="podman", linux=True, selinux=True)


def test_docker(tmp_path):
    a = argv(tmp_path, network=True, podman="docker", linux=True, selinux=False)
    assert a[0] == "docker" and f"--user={os.getuid()}:{os.getgid()}" in a and "--userns=keep-id" not in a
    assert "--network=bridge" in a and "label=disable" not in a and not any(x.endswith(":O") for x in a)


def test_podman_on_macos(tmp_path):
    a = argv(tmp_path, network=True, podman="podman", linux=False, selinux=False)
    assert "--network=bridge" in a and "--userns=keep-id" in a and "label=disable" not in a


def test_the_runtime_comes_from_the_hub(tmp_path, monkeypatch):
    monkeypatch.setenv("GAIFA_CONTAINER_RUNTIME", "docker")
    assert Sandbox(tmp_path).podman == "docker"
