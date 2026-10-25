"""Loaded by every Python process in the vLLM container (the vllm mod puts this folder on PYTHONPATH).
It runs inside kyuz0's image, with the image's Python, not the adapter's.

Why: in the pinned image (ROCm from TheRock on gfx1151), GPU event timing is broken: zeroing 256 MB
measures 0.005 ms by events and 2.4 ms by the wall clock. Triton's autotuner sizes its benchmark
from that estimate (`rep / estimate_ms`), so it ran ~381,000 repetitions per config, each with a
256 MB cache flush: minutes per config, hours for a hybrid model's linear-attention kernels on its
first start (plan 18.7). When the self-check finds events off by more than 5x, `do_bench` times with
the wall clock (synchronize + perf_counter) and a capped repetition count instead.

VLLM_MOD_TRITON_BENCH: auto (default) | wall | off.
"""

from __future__ import annotations

import importlib.abc
import importlib.util
import os
import sys

MODE = os.environ.get("VLLM_MOD_TRITON_BENCH", "auto")


def _wall_do_bench(original):
    import time

    from triton import runtime
    from triton.testing import _summarize_statistics

    state = {"broken": None}

    def check(di, cache) -> bool:
        ev0, ev1 = di.Event(enable_timing=True), di.Event(enable_timing=True)
        di.synchronize()
        t = time.perf_counter()
        ev0.record()
        for _ in range(3):
            runtime.driver.active.clear_cache(cache)
        ev1.record()
        di.synchronize()
        wall = (time.perf_counter() - t) * 1000
        events = ev0.elapsed_time(ev1)
        broken = events * 5 < wall
        print(f"gaifa: GPU events time a cache flush at {events:.4f} ms, the wall clock at {wall:.3f} ms; "
              f"Triton benchmarks use {'the wall clock' if broken else 'events'}", file=sys.stderr, flush=True)
        return broken

    def do_bench(fn, warmup=25, rep=100, grad_to_none=None, quantiles=None, return_mode="mean"):
        di = runtime.driver.active.get_device_interface()
        cache = runtime.driver.active.get_empty_cache_for_benchmark()
        if state["broken"] is None:
            state["broken"] = MODE == "wall" or check(di, cache)
        if not state["broken"]:
            return original(fn, warmup=warmup, rep=rep, grad_to_none=grad_to_none, quantiles=quantiles,
                            return_mode=return_mode)
        fn()
        di.synchronize()
        t = time.perf_counter()
        for _ in range(3):
            fn()
        di.synchronize()
        est = max((time.perf_counter() - t) * 1000 / 3, 1e-3)
        for _ in range(min(max(1, int(warmup / est)), 20)):
            fn()
        times = []
        for _ in range(min(max(3, int(rep / est)), 50)):
            if grad_to_none is not None:
                for x in grad_to_none:
                    x.grad = None
            runtime.driver.active.clear_cache(cache)
            di.synchronize()
            t = time.perf_counter()
            fn()
            di.synchronize()
            times.append((time.perf_counter() - t) * 1000)
        return _summarize_statistics(times, quantiles, return_mode)

    return do_bench


class _PatchTritonTesting(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """Patches triton.testing right after it is imported (importing triton here would slow every
    process in the container, and not all of them use it)."""

    def find_spec(self, name, path, target=None):
        if name != "triton.testing":
            return None
        sys.meta_path.remove(self)
        try:
            spec = importlib.util.find_spec(name)
        finally:
            sys.meta_path.insert(0, self)
        if spec is None or spec.loader is None:
            return None
        self._inner = spec.loader
        spec.loader = self
        return spec

    def create_module(self, spec):
        return self._inner.create_module(spec)

    def exec_module(self, module):
        self._inner.exec_module(module)
        try:
            module.do_bench = _wall_do_bench(module.do_bench)
        except Exception as e:  # noqa: BLE001  (never break the engine over a benchmark patch)
            print(f"gaifa: Triton benchmark patch not applied: {e}", file=sys.stderr, flush=True)


if MODE != "off":
    sys.meta_path.insert(0, _PatchTritonTesting())

# The image's own sitecustomize (Ubuntu's apport hook), which this one shadows.
_theirs = "/usr/lib/python3.12/sitecustomize.py"
if os.path.exists(_theirs):
    try:
        exec(compile(open(_theirs).read(), _theirs, "exec"), {"__name__": "sitecustomize_image"})
    except Exception:  # noqa: BLE001
        pass
