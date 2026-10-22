"""The system around the GPUs (plan 35.1): distro, kernel, CPU, memory, container, package manager."""

from __future__ import annotations

from .source import Source, first_match

LIB_DIRS = ("/usr/lib64", "/usr/lib/x86_64-linux-gnu", "/usr/lib/aarch64-linux-gnu", "/usr/lib", "/usr/local/lib", "/opt/rocm/lib")
PKG = (("dnf", "dnf"), ("apt-get", "apt"), ("zypper", "zypper"), ("pacman", "pacman"), ("brew", "brew"))


def os_release(src: Source) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in (src.read("/etc/os-release") or "").splitlines():
        key, _, value = line.partition("=")
        if key in ("ID", "VERSION_ID", "PRETTY_NAME", "ID_LIKE"):
            out[{"ID": "id", "VERSION_ID": "version", "PRETTY_NAME": "name", "ID_LIKE": "like"}[key]] = value.strip().strip('"')
    return out


def darwin_release(src: Source) -> dict[str, str]:
    version = (src.run(["sw_vers", "-productVersion"]) or "").strip()
    return {"id": "macos", "version": version, "name": f"macOS {version}".strip()}


def ram_bytes(src: Source, system: str) -> int:
    if system == "darwin":
        v = (src.run(["sysctl", "-n", "hw.memsize"]) or "").strip()
        return int(v) if v.isdigit() else 0
    kb = first_match(r"^MemTotal:\s+(\d+)", src.read("/proc/meminfo", 512))
    return int(kb) * 1024 if kb else 0


def cpu_name(src: Source, system: str) -> str:
    if system == "darwin":
        return (src.run(["sysctl", "-n", "machdep.cpu.brand_string"]) or "").strip()
    return first_match(r"^model name\s*:\s*(.+)$", src.read("/proc/cpuinfo", 4096)) or ""


def container(src: Source) -> str:
    if src.read("/run/.toolboxenv", 64) is not None:
        return "toolbox"
    if src.read("/run/.containerenv", 64) is not None:
        return "podman"
    if src.read("/.dockerenv", 64) is not None:
        return "docker"
    return ""


def package_manager(src: Source) -> str:
    for cmd, name in PKG:
        if src.which(cmd):
            return name
    return ""


def libs(src: Source, name: str) -> list[str]:
    """Paths of a shared library (`libze_loader.so`) in the usual folders."""
    out: list[str] = []
    for d in LIB_DIRS:
        out += src.glob(f"{d}/{name}*")
    return out


def lib_version(paths: list[str]) -> str:
    """The longest version suffix among a library's files: libamdhip64.so.7.1.52802 → 7.1."""
    best = ""
    for p in paths:
        tail = p.rsplit(".so.", 1)[1] if ".so." in p else ""
        if tail.count(".") > best.count("."):
            best = tail
    return ".".join(best.split(".")[:2]) if best else ("yes" if paths else "")
