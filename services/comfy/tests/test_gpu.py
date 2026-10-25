"""Plan 31.3: runs take GAIFA's GPU slot (a fake hub) before memory and ComfyUI, wait while another mod
holds it, give it back when the prompt ends, and run under a caller's lease (X-GAIFA-GPU-Lease)."""

import time

from test_run import env, run  # noqa: F401  (env is a fixture)


def until(cond, timeout=6):
    t0 = time.monotonic()
    while not cond() and time.monotonic() - t0 < timeout:
        time.sleep(0.05)
    return cond()


def test_a_run_waits_for_the_slot_then_runs(env):
    c, fake, hub, _ = env
    hub.gpu_busy = True
    before = len(fake.prompts)
    r = c.post("/v1/run", json={"workflow": "zimage", "inputs": {"prompt": "a fox"}})
    assert r.status_code == 202
    job = r.json()
    assert job["state"] == "queued" and job["stage"] == "waiting_gpu" and job["eta_s"] == 240
    assert job["ahead"][0]["service"] == "gen3d"
    assert len(fake.prompts) == before and not hub.acquires          # no memory asked, nothing queued in ComfyUI
    st = c.get("/v1/status").json()
    mine = next(j for j in st["jobs"] if j["id"] == job["id"])
    assert mine["stage"] == "waiting_gpu" and mine["ahead"]
    assert c.get(f"/v1/jobs/{job['id']}").json()["stage"] == "waiting_gpu"
    hub.gpu_busy = False
    done = c.get(f"/v1/jobs/{job['id']}", params={"wait": 10}).json()
    assert done["state"] == "done" and "stage" not in done
    assert len(fake.prompts) == before + 1 and hub.acquires                # memory after the slot
    lease = hub.gpu_acquires[-1]["lease"]
    assert hub.gpu_acquires[-1]["service"] == "comfy" and hub.gpu_acquires[-1]["class"] == "job"
    assert until(lambda: lease in hub.gpu_released)


def test_the_slot_is_held_until_the_prompt_ends(env):
    c, fake, hub, _ = env
    fake.hold = True
    r = c.post("/v1/run", json={"workflow": "zimage", "inputs": {"prompt": "slow"}}).json()
    lease = hub.gpu_acquires[-1]["lease"]
    time.sleep(0.3)
    assert lease in hub.gpu_held and lease not in hub.gpu_released
    assert c.post(f"/v1/queue/{r['id']}/cancel").json()["state"] == "cancelled"
    assert until(lambda: lease in hub.gpu_released)
    fake.hold = False


def test_cancel_while_waiting_gives_the_lease_back(env):
    c, fake, hub, _ = env
    hub.gpu_busy = True
    before = len(fake.prompts)
    job = c.post("/v1/run", json={"workflow": "zimage", "inputs": {"prompt": "never"}}).json()
    lease = hub.gpu_acquires[-1]["lease"]
    assert c.post(f"/v1/queue/{job['id']}/cancel").json()["state"] == "cancelled"
    assert until(lambda: lease in hub.gpu_released)
    hub.gpu_busy = False
    time.sleep(0.3)
    assert len(fake.prompts) == before and c.get(f"/v1/jobs/{job['id']}").json()["state"] == "cancelled"


def test_a_failed_prompt_releases(env):
    c, fake, hub, _ = env
    fake.fail_node = "70"
    job = run(c, {"workflow": "zimage", "inputs": {"prompt": "breaks"}})
    assert job["state"] == "failed"
    lease = hub.gpu_acquires[-1]["lease"]
    assert until(lambda: lease in hub.gpu_released)


def test_needs_room_after_a_wait_fails_the_run(env, monkeypatch):
    import comfy.run
    monkeypatch.setattr(comfy.run, "ROOM_WAIT_S", 0.01)
    c, fake, hub, _ = env
    hub.gpu_busy, hub.room = True, False
    job = c.post("/v1/run", json={"workflow": "zimage", "inputs": {"prompt": "x"}}).json()
    assert job["stage"] == "waiting_gpu"
    hub.gpu_busy = False
    done = c.get(f"/v1/jobs/{job['id']}", params={"wait": 10}).json()
    assert done["state"] == "failed" and "memory" in done["error"].lower()
    assert until(lambda: hub.gpu_acquires[-1]["lease"] in hub.gpu_released)


def test_a_callers_lease_is_the_parent(env):
    c, fake, hub, _ = env
    hub.gpu_busy = True                      # another group holds the slot: our caller (gen3d) is that holder
    r = c.post("/v1/run", json={"workflow": "zimage", "inputs": {"prompt": "nested"}},
               headers={"X-GAIFA-GPU-Lease": "gl_parent0000"})
    assert r.status_code == 202 and "stage" not in r.json()
    assert hub.gpu_acquires[-1]["parent"] == "gl_parent0000"
    assert c.get(f"/v1/jobs/{r.json()['id']}", params={"wait": 10}).json()["state"] == "done"
