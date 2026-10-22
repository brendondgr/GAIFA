"""The facts `utils/proc.py` reads from /proc, through psutil, for systems without /proc (macOS)
(plan 35.3). GPU memory and engine time per process aren't readable there: they count as 0, and
the memory manager uses what a mod acquired or its estimate instead (plan 36.1)."""

from __future__ import annotations

from collections.abc import Iterable


def _ps():
    import psutil    # imported on first use: nothing runs at import

    return psutil


def meminfo() -> dict[str, int]:
    vm = _ps().virtual_memory()
    return {"total_bytes": vm.total, "used_bytes": vm.total - vm.available, "available_bytes": vm.available}


def process_tree(pid: int) -> list[int]:
    ps = _ps()
    try:
        p = ps.Process(pid)
        return [pid] + [c.pid for c in p.children(recursive=True)]
    except (ps.NoSuchProcess, ps.AccessDenied):
        return []


def rss_bytes(pid: int) -> int:
    ps = _ps()
    try:
        return ps.Process(pid).memory_info().rss
    except (ps.NoSuchProcess, ps.AccessDenied):
        return 0


def pss_bytes(pid: int) -> int:
    """Linux has PSS; elsewhere `uss` (memory only this process holds) is the closest that sums
    without double counting, and RSS when even that isn't allowed."""
    ps = _ps()
    try:
        full = ps.Process(pid).memory_full_info()
        return getattr(full, "pss", None) or getattr(full, "uss", 0) or full.rss
    except ps.AccessDenied:
        return rss_bytes(pid)
    except ps.NoSuchProcess:
        return 0


def footprint(pids: Iterable[int]) -> int:
    every: list[int] = []
    for pid in pids:
        every.extend(p for p in process_tree(pid) if p not in every)
    return sum(pss_bytes(p) for p in every)


def describe(pid: int) -> dict[str, object]:
    ps = _ps()
    try:
        p = ps.Process(pid)
        return {"pid": pid, "name": p.name(), "cmdline": " ".join(p.cmdline())}
    except (ps.NoSuchProcess, ps.AccessDenied):
        return {"pid": pid, "name": "?", "cmdline": ""}


def port_owner(port: int) -> dict[str, object] | None:
    """The process listening on `port`, among the processes this user may inspect (macOS lets an
    unprivileged user list only their own processes' sockets)."""
    ps = _ps()
    for p in ps.process_iter(["pid"]):
        try:
            for c in p.net_connections(kind="inet"):
                if c.status == ps.CONN_LISTEN and c.laddr and c.laddr.port == port:
                    return describe(p.pid)
        except (ps.NoSuchProcess, ps.AccessDenied, ps.ZombieProcess):
            continue
    return None
