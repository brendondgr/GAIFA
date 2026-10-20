"""The GPU idle sources: other processes' DRM engine time (the default) and gpu_busy_percent."""

from __future__ import annotations

from embed.gpu import EngineMeter, GpuIdle, engine_counters, read_busy


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def test_engine_meter_counts_other_processes_only():
    clock, snap = Clock(), {}
    meter = EngineMeter(exclude=lambda: {100}, counters=lambda: snap, clock=clock)
    snap.update({"7": ({200}, {"gfx": 0, "compute": 0}), "8": ({100}, {"gfx": 0})})
    assert meter() is None                                          # the first read is a snapshot
    clock.t = 1.0
    snap.update({"7": ({200}, {"gfx": 500_000_000, "compute": 100_000_000}), "8": ({100}, {"gfx": 900_000_000})})
    assert meter() == 50                                            # the busiest engine of other processes
    clock.t = 2.0
    snap["9"] = ({300}, {"gfx": 10**12})                            # opened since: counted from the next read
    assert meter() == 0
    clock.t = 2.5
    snap["9"] = ({300}, {"gfx": 10**12 + 10**9})                    # a full second of work in half a second
    assert meter() == 100


def test_shared_client_follows_its_pids():
    """A client open in our process and a forked one is ours."""
    clock, snap = Clock(), {"5": ({100, 101}, {"gfx": 0})}
    meter = EngineMeter(exclude=lambda: {100}, counters=lambda: snap, clock=clock)
    meter()
    clock.t = 1
    snap["5"] = ({100, 101}, {"gfx": 10**9})
    assert meter() == 0


def test_with_gpu_idle_and_on_this_machine():
    clock, snap = Clock(), {"1": ({9}, {"gfx": 0})}
    gpu = GpuIdle(10, 5, read=EngineMeter(exclude=set, counters=lambda: snap, clock=clock), clock=clock,
                  sleep=lambda s: None)
    gpu.sample()                                                    # None: no reading yet, not busy
    for t in range(1, 7):
        clock.t = t
        snap["1"] = ({9}, {"gfx": t * 20_000_000})                  # 2 % busy
        gpu.sample()
    assert gpu.idle() and gpu.last == 2
    assert isinstance(engine_counters(), dict)                      # reads this machine's /proc without failing
    v = read_busy()
    assert v is None or 0 <= v <= 100
