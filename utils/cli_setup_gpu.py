"""The GPU part of `gaifa setup host` (plan 37.3), per kind of machine. Standard library only.

- **AMD that shares the system's memory** (Strix Halo and other APUs): GTT kernel parameters, the IOMMU,
  the GTT size, the `video` and `render` groups (today's checks, docs/setup/host.md).
- **An AMD card:** the groups and `/dev/kfd`.
- **NVIDIA:** the driver answers `nvidia-smi`; with containers, the NVIDIA Container Toolkit's CDI spec.
- **Intel:** the `render` group and the compute runtime (Level Zero) PyTorch's xpu needs.
- **WSL2:** systemd is on, the clone isn't on a Windows drive (`/mnt/…`), `/dev/dxg` exists.
- **macOS:** Apple Silicon, Homebrew.
Every check here has `gpu = True`, so it only blocks plans with GPU mods. Fixes that need root are printed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

GTT_MIB, PAGES = "131072", "33554432"     # host.md §1: 128 GiB
GPU_PARAMS = f"amdgpu.gttsize={GTT_MIB} ttm.pages_limit={PAGES}"
CDI = ("/etc/cdi/nvidia.yaml", "/var/run/cdi/nvidia.yaml")
DRIVER_FIX = {"apt": "sudo ubuntu-drivers install   (or your distribution's NVIDIA driver package), then reboot",
              "dnf": "sudo dnf install akmod-nvidia   (from RPM Fusion), then reboot",
              "pacman": "sudo pacman -S nvidia, then reboot", "zypper": "sudo zypper install nvidia-video-G06, then reboot"}
INTEL_RUNTIME = {"apt": "sudo apt install intel-opencl-icd libze1 libze-intel-gpu1",
                 "dnf": "sudo dnf install intel-compute-runtime oneapi-level-zero",
                 "pacman": "sudo pacman -S intel-compute-runtime level-zero-loader",
                 "zypper": "sudo zypper install intel-opencl level-zero"}


def amd_unified(probe: Any, Check: Any) -> list[Any]:
    out = []
    params = dict(p.split("=", 1) if "=" in p else (p, "") for p in probe.cmdline().split())
    missing = [k for k in ("amdgpu.gttsize", "ttm.pages_limit") if k not in params]
    out.append(Check("kernel-gtt", not missing, "the GPU may use most of the memory (GTT)" if not missing else f"{', '.join(missing)} not set",
                     "" if not missing else f'sudo grubby --update-kernel=ALL --args="{GPU_PARAMS}" && sudo reboot', needs_root=True, gpu=True))
    iommu_off = params.get("amd_iommu") == "off"
    out.append(Check("iommu-on", not iommu_off, "the IOMMU is on" if not iommu_off else "amd_iommu=off: nothing stops a stray GPU write (host.md §1)",
                     "" if not iommu_off else 'sudo grubby --update-kernel=ALL --remove-args="amd_iommu=off" && sudo reboot', needs_root=True, gpu=True))
    gtt, mem = probe.gtt_bytes(), probe.mem_bytes()
    enough = gtt >= 0.75 * mem if mem else gtt >= 96e9   # the default GTT is half the memory; host.md wants most of it
    out.append(Check("gtt-size", bool(gtt) and enough, f"GTT {gtt / 2**30:.1f} GiB of {mem / 2**30:.0f} GiB" if gtt else "no GPU memory reported (/sys/class/drm/card*/device/mem_info_gtt_total)",
                     "" if gtt and enough else "set the kernel parameters above and reboot; check with: cat /sys/class/drm/card*/device/mem_info_gtt_total", gpu=True))
    return out


def groups(probe: Any, Check: Any, want: tuple[str, ...]) -> Any:
    have = probe.groups()
    lacking = [g for g in want if g not in have]
    return Check("gpu-groups", not lacking, f"in the {' and '.join(want)} group{'s' if len(want) > 1 else ''}" if not lacking else f"not in {', '.join(lacking)}",
                 "" if not lacking else f"sudo usermod -aG {','.join(want)} $USER  (then log out and in)", needs_root=True, gpu=True)


def checks(probe: Any, machine: Any, root: Path, needs: set[str], Check: Any) -> list[Any]:
    """The GPU checks for this machine, in order (`Check` is cli_setup_host.Check)."""
    out: list[Any] = []
    pkg = machine.pkg
    if machine.wsl:
        from_platform = _wsl_systemd()
        out.append(Check("wsl-systemd", from_platform is None, "WSL runs systemd" if from_platform is None else "WSL runs without systemd",
                         "" if from_platform is None else from_platform.split("\n", 1)[-1].strip(), needs_root=True))
        on_windows = str(root.resolve()).startswith("/mnt/")
        out.append(Check("wsl-clone", not on_windows, "the clone is in WSL's own filesystem" if not on_windows else f"the clone ({root}) is on a Windows drive: everything is many times slower there",
                         "" if not on_windows else "clone GAIFA again under your WSL home folder (~/), not /mnt/c/…"))
        dxg = not any("dxg" in p for g in machine.gpus for p in g.problems)
        out.append(Check("wsl-gpu", dxg and bool(machine.gpus), "WSL sees the GPU (/dev/dxg)" if dxg and machine.gpus else "WSL doesn't see a GPU",
                         "" if dxg and machine.gpus else "update WSL (`wsl --update` in PowerShell) and the GPU driver on Windows", gpu=True))
    for g in machine.gpus:
        if g.vendor == "amd" and not machine.wsl:
            if g.memory == "unified":
                out += amd_unified(probe, Check)
                out.append(groups(probe, Check, ("video", "render")))
            else:
                out.append(groups(probe, Check, ("video", "render")))
                kfd = "rocm" in g.accels
                out.append(Check("amd-kfd", kfd, "ROCm reaches the GPU (/dev/kfd)" if kfd else "; ".join(g.problems) or "ROCm can't reach the GPU",
                                 "" if kfd else "use a kernel with the amdgpu driver's compute support (/dev/kfd); see host-linux-amd.md", gpu=True))
        elif g.vendor == "nvidia":
            ok = "cuda" in g.accels
            out.append(Check("nvidia-driver", ok, f"NVIDIA driver {g.driver}, CUDA {g.runtimes.get('cuda', '?')}" if ok else "; ".join(g.problems) or "the NVIDIA driver doesn't answer",
                             "" if ok else ("update the NVIDIA driver on Windows (WSL uses it; don't install one inside Linux)" if machine.wsl else DRIVER_FIX.get(pkg, "install the NVIDIA driver, then reboot")),
                             needs_root=not ok and not machine.wsl, gpu=True))
            if needs & {"podman", "docker"}:
                cdi = any(Path(p).exists() for p in CDI) if probe.which("nvidia-ctk") else False
                out.append(Check("nvidia-cdi", cdi, "containers can use the GPU (NVIDIA Container Toolkit, CDI)" if cdi else "containers can't use the GPU yet",
                                 "" if cdi else "install nvidia-container-toolkit, then: sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml", needs_root=True, gpu=True))
        elif g.vendor == "intel":
            if not machine.wsl:
                out.append(groups(probe, Check, ("render",)))
            ok = "xpu" in g.accels
            out.append(Check("intel-runtime", ok, f"Intel's compute runtime (Level Zero {g.runtimes.get('level_zero', '')})" if ok else "Intel's compute runtime isn't installed",
                             "" if ok else INTEL_RUNTIME.get(pkg, "install Intel's compute runtime (Level Zero) for your distribution"), needs_root=not ok, gpu=True))
    if machine.os == "darwin":
        arm = machine.arch in ("arm64", "aarch64")
        out.append(Check("apple-silicon", arm, "Apple Silicon: PyTorch reaches the GPU (mps)" if arm else "an Intel Mac: the GPU mods run on the CPU here",
                         "" if arm else "nothing to fix: choose mods that run on the CPU", gpu=True))
        brew = probe.which("brew")
        out.append(Check("homebrew", brew, "Homebrew is installed" if brew else "Homebrew is missing (the fixes below use it)",
                         "" if brew else '/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'))
    if not machine.gpus and machine.os != "darwin":
        out.append(Check("gpu", True, "no GPU found: only mods with a CPU variant can run here (gaifa hardware)", gpu=True))
    return out


def _wsl_systemd() -> str | None:
    if __package__:
        from utils import cli_platform
    else:
        import cli_platform  # type: ignore[no-redef]
    return cli_platform.wsl_systemd_fix()
