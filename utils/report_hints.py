"""What a field report reads into failures (plan 40.2): known error patterns with their likely cause and
where a fix usually goes, and the redaction every report goes through. Standard library only.

`hints(text)` → the patterns that match, most specific first. `redact(text, home)` hides tokens, keys and
passwords, and writes the home folder as `~`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Hint:
    id: str
    pattern: re.Pattern[str]
    cause: str
    fix: str          # where a fix usually goes, for the fixer


def _h(id_: str, pattern: str, cause: str, fix: str) -> Hint:
    return Hint(id_, re.compile(pattern, re.I | re.M), cause, fix)


HINTS: list[Hint] = [
    _h("cuda-driver", r"CUDA driver version is insufficient|forward compatibility was attempted|no kernel image is available|"
       r"is not compatible with the current PyTorch installation|CUDA capability sm_\d+ is not compatible",
       "PyTorch's CUDA build doesn't match the NVIDIA driver or the GPU's architecture",
       "the CUDA flavour chosen in torch_index.py (cuda_flavour) against `nvidia-smi`'s CUDA Version; or a newer driver"),
    _h("rocm-arch", r"hipErrorNoBinaryForGpu|HSA_STATUS_ERROR|invalid device function|No HIP GPUs are available|"
       r"amdgpu.*gfx\w+ is not supported",
       "the ROCm build has no code for this GPU's gfx target",
       "the ROCm family index in torch_index.py (ROCM_FAMILY), or the variant's lock (made for gfx1151)"),
    _h("cuda-toolkit", r"nvcc: (command )?not found|No CUDA toolkit found|CUDA_HOME environment variable is not set|"
       r"Could not find nvcc|needs the CUDA toolkit's nvcc",
       "a source build needs the CUDA toolkit (nvcc), which isn't installed or on PATH",
       "docs/setup/host-linux-nvidia.md, or the variant's `needs` (add nvcc) and its steps"),
    _h("container-gpu", r"could not select device driver|nvidia-container-cli|unresolvable CDI devices|CDI device|"
       r"Error: setting up CDI devices|no such file or directory: /dev/(kfd|dri|dxg)",
       "the container can't reach the GPU (the NVIDIA Container Toolkit's CDI spec, or a missing device node)",
       "services/_template/containers.py (gpu_args) and the mod's copy; host-linux-nvidia.md §2"),
    _h("missing-lib", r"lib[\w.+-]+\.so[\d.]*: cannot open shared object file|Library not loaded|"
       r"could not load library|cannot find -l\w+|OSError: lib\S+: cannot open",
       "a shared library is missing (a system package, or a pip package's library not on the loader's path)",
       "the variant's install step (a package to add), or the manifest's [run.variants.<accel>] env (LD_LIBRARY_PATH)"),
    _h("level-zero", r"ze_loader|libze_intel_gpu|Level Zero|XPU device count is zero|No XPU devices",
       "Intel's compute runtime (Level Zero) isn't installed or doesn't see the GPU",
       "docs/setup/host-linux-intel.md §1, utils/cli_setup_gpu.py (INTEL_RUNTIME)"),
    _h("mps-op", r"not (currently )?implemented for (the )?['\"]?MPS|MPS backend out of memory|PYTORCH_ENABLE_MPS_FALLBACK",
       "an operation has no Apple GPU (MPS) kernel",
       "set PYTORCH_ENABLE_MPS_FALLBACK=1 in the variant's env, or use the cpu variant"),
    _h("oom", r"out of memory|OutOfMemoryError|Cannot allocate memory|Killed$|exit (code )?137\b|MemoryError",
       "the machine ran out of GPU or system memory",
       "a smaller model, the mod's memory estimate ([memory] estimate_gb / vram_gb), or fewer mods loaded"),
    _h("no-package", r"No matching distribution found|Could not find a version that satisfies|"
       r"no version of \S+ (==|satisfies)|Because \S+ (was not found|has no wheels)|has no wheels with a matching|"
       r"is not available for this platform|unsupported platform tag",
       "a Python package has no build for this platform, Python version or wheel index",
       "the variant's lock or requirements, and the index it installs from (torch_index.py)"),
    _h("no-systemd", r"System has not been booted with systemd|Failed to connect to bus|systemctl: command not found|"
       r"systemd-run: command not found",
       "this machine has no systemd user manager (WSL without systemd, or macOS)",
       "docs/setup/host-wsl2.md §1; a mod that calls systemctl itself needs a [run.variants] env or its own fallback"),
    _h("permission-gpu", r"Permission denied.*/dev/(kfd|dri|nvidia|dxg)|/dev/(kfd|dri)\S*: Permission denied",
       "your user may not use the GPU device",
       "the groups (video, render): utils/cli_setup_gpu.py's gpu-groups fix"),
    _h("port", r"address already in use|port \d+ is already in use|Errno 98",
       "a port is taken by another program", "`gaifa doctor` names the owner; [services.<id>] port in config.toml"),
    _h("network", r"Temporary failure in name resolution|Could not resolve host|Connection (refused|timed out|reset)|"
       r"Network is unreachable|SSL(Error|: )|Read timed out|curl: \(\d+\)",
       "a download failed (network, a moved URL, or a server that refused)",
       "retry; if the URL moved, the step's run line in its setup doc"),
    _h("gated", r"401 Client Error|403 Client Error|Access to model \S+ is restricted|gated repo|"
       r"You must have access to it|Repository Not Found",
       "a Hugging Face repo is gated or missing (accept its terms, log in)",
       "the setup doc's login step and the suggestion's `gated`"),
    _h("missing-command", r"command not found|: not found$|No such file or directory: '[\w./-]+'|"
       r"executable file not found|needs (git|cmake|uv|nvcc|python3)",
       "a command the step uses isn't installed",
       "the setup doc's (or variant's) `needs`, and utils/cli_setup_pkgs.py's package names"),
    _h("pip-system", r"externally-managed-environment", "a system Python refused pip",
       "the step should use the mod's venv (uv) instead of the system's Python"),
    _h("git", r"fatal: (unable to access|could not read|reference is not a tree|remote error)|did not match any file|"
       r"pathspec .* did not match", "a git clone or checkout failed (a moved repo, or a commit that's gone)",
       "the pinned repo and commit in the step"),
    _h("toolbox", r"toolbox: command not found|Error: container \S+ not found|crun: .* is not running",
       "the ROCm toolbox path ran on a machine that isn't gfx1151", "the comfy variant (bin/comfyui runtime)"),
]


def hints(text: str) -> list[Hint]:
    """The known patterns in `text` (a log's tail), in the table's order."""
    return [h for h in HINTS if h.pattern.search(text or "")]


SECRET_SHAPES = [
    re.compile(r"\bhf_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bsk-(?:proj-|ant-)?[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bxox[abpr]-[A-Za-z0-9-]{10,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),   # JWTs
]
SECRET_VALUE = re.compile(r"(?i)\b([A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|PASSWD|API_?KEY|ACCESS_KEY|AUTH)[A-Z0-9_]*)(\s*[=:]\s*)(\"[^\"]*\"|'[^']*'|\S+)")
BEARER = re.compile(r"(?i)(Authorization:\s*(?:Bearer|Basic)\s+)\S+")


def redact(text: str, home: str = "") -> str:
    """Tokens, keys and passwords out; the home folder as ~."""
    out = text or ""
    for rx in SECRET_SHAPES:
        out = rx.sub("<redacted>", out)
    out = BEARER.sub(lambda m: m.group(1) + "<redacted>", out)
    out = SECRET_VALUE.sub(lambda m: m.group(0) if m.group(3) == "<redacted>" or m.group(1).lower() == "authorization"
                           else f"{m.group(1)}{m.group(2)}<redacted>", out)
    if home and len(home) > 1:
        out = out.replace(home.rstrip("/") + "/", "~/").replace(home.rstrip("/"), "~")
    return out
