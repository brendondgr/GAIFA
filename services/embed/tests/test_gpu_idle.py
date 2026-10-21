"""The GPU idle measures: `aihub` (other GPU mods working, their Vulkan engine time, and the device's median;
the default) and `device` (gpu_busy_percent's median)."""

from __future__ import annotations

import httpx

from embed.gpu import DeviceMedian, GpuIdle, HubMeter, read_busy


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


class FakeHub:
    def __init__(self):
        self.services = [{"id": "embed", "load": "loaded", "state": "ready", "busy": True},
                         {"id": "comfy", "load": "unloaded", "state": "ready", "busy": False, "in_flight": 0, "jobs": []},
                         {"id": "agent", "load": "n/a", "state": "ready", "busy": True}]   # no [memory]: not a GPU mod
        self.memory = {"by_service": [{"id": "embed", "gpu_busy_pct": 90.0}, {"id": "lcpp", "gpu_busy_pct": 0.0}]}

    def get(self, url):
        return self.services if url.endswith("/api/services") else self.memory


def meter(hub, device=14, **kw):
    return HubMeter("http://hub", "embed", device=lambda: device, get=hub.get, **kw)


def test_quiet_when_only_ourselves_and_non_gpu_mods_work():
    hub = FakeHub()
    m = meter(hub)
    assert m() == 0 and m.detail["mods_working"] == [] and m.detail["device_median_pct"] == 14


def test_another_gpu_mod_working_is_busy():
    hub = FakeHub()
    m = meter(hub)
    for change in ({"busy": True}, {"in_flight": 1}, {"jobs": [{"state": "running"}]}):
        hub.services[1] = {"id": "comfy", "load": "loaded", "state": "ready", "busy": False, "in_flight": 0, "jobs": [], **change}
        assert m() == 100 and m.detail["mods_working"] == ["comfy"]
    hub.services[1]["state"] = "stopped"
    assert m() == 0


def test_vulkan_engine_time_and_the_device():
    hub = FakeHub()
    hub.memory["by_service"][1]["gpu_busy_pct"] = 35.0                  # lcpp generating (Vulkan)
    assert meter(hub)() == 35
    assert meter(FakeHub(), device=45)() == 100                         # the whole GPU busy: someone else's work
    def down(url):
        raise httpx.ConnectError("refused")
    assert HubMeter("http://hub", device=lambda: 14, get=down)() == 0    # no hub: the device part alone
    assert HubMeter("http://hub", device=lambda: None, get=down)() is None


def test_device_median_ignores_spikes():
    clock, vals = Clock(), iter([14, 15, 88, 14, 16, 90, 15])
    d = DeviceMedian(30, read=lambda: next(vals), clock=clock)
    out = []
    for t in range(7):
        clock.t = t * 5
        out.append(d())
    assert out[-1] == 15                                                # spikes to 88 and 90 aren't the median
    clock.t = 100
    d.read = lambda: 60
    assert d() == 60                                                    # old readings left the window


def test_gate_with_the_aihub_measure():
    clock, hub = Clock(), FakeHub()
    gpu = GpuIdle(10, 5, read=meter(hub), clock=clock, sleep=lambda s: None)
    hub.services[1].update(busy=True)
    gpu.sample()
    assert not gpu.idle()
    hub.services[1].update(busy=False)
    for t in range(1, 7):
        clock.t = t
        gpu.sample()
    assert gpu.idle() and gpu.last == 0
    hub.services[1].update(in_flight=2)
    assert gpu.busy_now() and not gpu.idle()                            # a request to comfy: wait again
    v = read_busy()
    assert v is None or 0 <= v <= 100


def test_a_pegged_gpu_counts_at_once():
    clock, vals = Clock(), iter([14] * 20 + [99, 100, 98] + [99] * 3)
    d = DeviceMedian(30, read=lambda: next(vals), clock=clock)
    for t in range(20):
        clock.t = t
        d()
    assert not d.pegged()
    for t in range(20, 23):
        clock.t = t
        d()
    assert d.pegged() and int(__import__("statistics").median(x for _, x in d.samples)) == 14   # the median is still 14
    hub = FakeHub()
    assert HubMeter("http://hub", device=d, get=hub.get)() == 100
