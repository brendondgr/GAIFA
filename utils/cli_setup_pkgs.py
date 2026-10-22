"""Package names per package manager, for the host checks' fixes (plan 37.3). Standard library only.

`fix(cmd, pkg)` is the command that installs what provides `cmd` with the machine's package manager, and
whether it needs root. Nothing here runs anything: the wizard prints the fix.
"""

from __future__ import annotations

# command → package, per manager. A missing entry means the package has the command's name.
NAMES: dict[str, dict[str, str]] = {
    "dnf": {"git": "git-core", "node": "nodejs22", "npm": "nodejs22-npm", "sha256sum": "coreutils", "systemd-run": "systemd",
            "vulkaninfo": "vulkan-tools"},
    "apt": {"toolbox": "podman-toolbox", "node": "nodejs", "sha256sum": "coreutils", "systemd-run": "systemd", "vulkaninfo": "vulkan-tools"},
    "zypper": {"node": "nodejs22", "npm": "npm22", "sha256sum": "coreutils", "systemd-run": "systemd", "vulkaninfo": "vulkan-tools"},
    "pacman": {"node": "nodejs", "sha256sum": "coreutils", "systemd-run": "systemd", "vulkaninfo": "vulkan-tools"},
    "brew": {"node": "node", "npm": "node", "sha256sum": "coreutils", "vulkaninfo": "vulkan-tools"},
}
INSTALL = {"dnf": "sudo dnf install {}", "apt": "sudo apt install {}", "zypper": "sudo zypper install {}",
           "pacman": "sudo pacman -S {}", "brew": "brew install {}"}
NOTES = {("dnf", "ffmpeg"): "   (the full ffmpeg is in RPM Fusion: host.md §3)"}
NONE_ON = {("brew", "toolbox"), ("brew", "systemd-run")}      # no such thing there


def package(cmd: str, pkg: str) -> str:
    return NAMES.get(pkg, {}).get(cmd, cmd)


def fix(cmd: str, pkg: str) -> tuple[str, bool]:
    """(the command to run, needs root). An unknown package manager gets a plain instruction."""
    if (pkg, cmd) in NONE_ON:
        return f"{cmd} isn't available on this system; a mod that needs it can't run here", False
    if pkg not in INSTALL:
        return f"install {cmd} with your system's package manager", True
    return INSTALL[pkg].format(package(cmd, pkg)) + NOTES.get((pkg, cmd), ""), pkg != "brew"
