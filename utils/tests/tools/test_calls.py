"""13.2: calls, permissions and approvals: schema errors with fixes, deny/ask/allow and modes,
approvals with edited arguments, denial, no bypass, result capping, media results and jobs."""

from __future__ import annotations

import asyncio

from utils import config
from utils.tools.approvals import decide


async def test_read_tool_runs_at_once_with_path_and_query(th):
    r = await th.call("fake_tools_get_item", {"item_id": "a b/c", "verbose": True})
    assert r["status"] == "done" and r["result"] == {"id": "a%20b%2Fc", "verbose": "true"}
    assert r["call_id"].startswith("call_")
    again = (await th.client.get(f"/api/tools/calls/{r['call_id']}")).json()
    assert again["status"] == "done" and again["result"]["verbose"] == "true"


async def test_invalid_arguments_name_the_field_and_the_fix(th):
    r = await th.call("fake_tools_make_image", {"aspect": "16:10", "steps": 99, "colour": "red"})
    assert r["status"] == "error" and r["error"]["code"] == "invalid_arguments"
    d, fix = r["error"]["detail"], r["error"]["fix"]
    assert "prompt is required" in d and "'16:10'" in d and "above the maximum 50" in d and "colour" in d
    assert "'16:9'" in fix and "use 50 or less" in fix
    r = await th.call("fake_tools_get_item", {"item_id": 5})
    assert r["error"]["code"] == "invalid_arguments" and "expected string" in r["error"]["detail"]
    r = await th.call("fake_tools_nope", {})
    assert r["status"] == "error" and r["error"]["code"] == "unknown_tool"


def test_permission_order_and_modes():
    cfg = config.Config()
    assert decide("x_read", "read", cfg)[0] == "allow"
    assert decide("x_gen", "generate", cfg)[0] == "ask"
    assert decide("x_w", "write", cfg)[0] == "ask"
    assert decide("x_d", "destructive", cfg)[0] == "ask"
    assert decide("hub_start_service", "write", cfg)[0] == "allow"
    assert decide("x_gen", "generate", cfg, "auto")[0] == "allow"
    assert decide("x_d", "destructive", cfg, "auto")[0] == "ask"
    assert decide("x_gen", "generate", cfg, "read_only")[0] == "deny"
    assert decide("x_read", "read", cfg, "read_only")[0] == "allow"
    cfg.agent.permissions.deny = ["comfy_*"]
    cfg.agent.permissions.ask = ["comfy_*", "x_read"]
    cfg.agent.permissions.allow = ["comfy_*", "x_gen"]
    assert decide("comfy_generate_image", "generate", cfg)[0] == "deny"     # deny beats ask and allow
    assert decide("x_read", "read", cfg)[0] == "ask"                        # ask beats the read default
    assert decide("x_gen", "generate", cfg)[0] == "allow"                   # allow beats the risk default


async def test_ask_creates_an_approval_and_runs_nothing(th):
    r = await th.call("fake_tools_make_image", {"prompt": "a fox", "aspect": "1:1"}, thread="t1")
    assert r["status"] == "needs_approval" and r["ask_fields"] == ["aspect", "steps"] and r["risk"] == "generate"
    assert r["schema"]["properties"]["aspect"]["enum"] and r["arguments"] == {"prompt": "a fox", "aspect": "1:1"}
    assert not list((th.root / "outputs").rglob("*.png"))
    pending = (await th.client.get("/api/approvals")).json()
    assert [a["id"] for a in pending] == [r["approval_id"]] and pending[0]["origin"] == {"thread": "t1"}
    assert pending[0]["schema"]["properties"]["prompt"]


async def test_approval_with_edited_arguments_runs_the_edit(th):
    r = await th.call("fake_tools_make_image", {"prompt": "a fox", "aspect": "1:1"})
    aid = r["approval_id"]
    bad = await th.client.post(f"/api/approvals/{aid}", json={"approve": True, "arguments": {"prompt": "a fox", "aspect": "4:5"}})
    assert bad.status_code == 422 and bad.json()["code"] == "invalid_arguments"
    assert (await th.client.get(f"/api/approvals/{aid}")).json()["state"] == "pending"   # still waiting
    ok = await th.client.post(f"/api/approvals/{aid}?wait=20", json={"approve": True, "arguments": {"prompt": "a fox", "aspect": "16:9", "steps": 4}})
    res = ok.json()
    assert res["status"] == "done" and res["result"]["aspect"] == "16:9" and res["result"]["steps"] == 4
    assert res["approval_id"] == aid
    [o] = res["outputs"]
    assert o["kind"] == "image" and o["ref"] == f"output:{o['output_id']}" and o["url"].endswith("/file")
    assert (await th.client.get(f"/api/outputs/{o['output_id']}")).status_code == 200
    a = (await th.client.get(f"/api/approvals/{aid}")).json()
    assert a["state"] == "approved" and a["final"]["aspect"] == "16:9" and a["arguments"]["aspect"] == "1:1"
    again = await th.client.post(f"/api/approvals/{aid}", json={"approve": True})
    assert again.status_code == 409 and again.json()["code"] == "already_decided"


async def test_denied_approval_runs_nothing(th):
    r = await th.call("fake_tools_make_image", {"prompt": "a cat"})
    d = (await th.client.post(f"/api/approvals/{r['approval_id']}", json={"approve": False, "reason": "not now"})).json()
    assert d["status"] == "denied" and d["error"]["code"] == "denied_by_user" and d["error"]["detail"] == "not now"
    assert not list((th.root / "outputs").rglob("*.png"))
    assert (await th.client.get("/api/approvals")).json() == []


async def test_modes_and_denies(th, tools_cfg):
    r = await th.call("fake_tools_make_image", {"prompt": "x"}, mode="read_only")
    assert r["status"] == "denied" and "Plan mode" in r["error"]["detail"]
    r = await th.call("fake_tools_make_image", {"prompt": "x"}, mode="auto")
    assert r["status"] == "done" and r["outputs"][0]["kind"] == "image"
    r = await th.call("fake_tools_wipe", {"jid": "j_9"}, mode="auto")
    assert r["status"] == "needs_approval"
    tools_cfg.agent.permissions.deny = ["fake_tools_get_*"]
    r = await th.call("fake_tools_get_item", {"item_id": "a"})
    assert r["status"] == "denied" and "permissions" in r["error"]["detail"]


async def test_no_bypass_for_ask_tools(th):
    """The call route has no way to skip approval: extra fields are refused, an approval id
    can't be reused for other arguments or another tool."""
    r = await th.client.post("/api/tools/fake_tools_make_image/call", json={"arguments": {"prompt": "x"}, "approved": True})
    assert r.status_code == 422
    first = await th.call("fake_tools_make_image", {"prompt": "x"})
    other = await th.call("fake_tools_say", {"text": "hi"})
    assert first["status"] == other["status"] == "needs_approval"
    # deciding one approval runs only its own tool
    res = (await th.client.post(f"/api/approvals/{other['approval_id']}?wait=10", json={"approve": True})).json()
    assert res["tool"] == "fake_tools_say"
    assert not list((th.root / "outputs").rglob("*.png"))


async def test_results_are_capped_and_readable_in_full(th):
    r = await th.call("fake_tools_big", {})
    assert r["status"] == "done" and r["result"]["truncated"] is True and r["result"]["full"].endswith("/result")
    page = (await th.client.get(f"/api/tools/calls/{r['call_id']}/result?offset=0&limit=100")).json()
    assert page["total"] > 8000 and len(page["text"]) == 100


async def test_binary_results_become_outputs(th):
    r = await th.call("fake_tools_say", {"text": "hello there"}, mode="auto")
    [o] = r["outputs"]
    assert o["kind"] == "audio" and r["result"]["content_type"] == "audio/wav"
    assert "hello there" in o["title"].lower()
    r = await th.call("fake_tools_beep", {}, mode="auto")   # not saved by the mod: the hub saves it
    [o] = r["outputs"]
    assert o["kind"] == "audio" and list((th.root / "outputs" / "fake-tools").rglob("*-beep.wav"))


async def test_job_followed_to_its_end_with_progress_events(th):
    seen = []
    sub = th.hub.bus.subscribe()

    async def watch():
        async for ev in sub:
            if ev.get("type") == "tool_call":
                seen.append(ev["call"])

    w = asyncio.create_task(watch())
    r = await th.call("fake_tools_render", {"prompt": "a scene", "seconds": 1.0}, mode="auto")
    w.cancel()
    assert r["status"] == "done" and r["result"]["state"] == "done" and r["outputs"][0]["kind"] == "image"
    assert any(e["status"] == "running" and e.get("job_id") for e in seen)
    assert seen[-1]["status"] == "done"
    failed = await th.call("fake_tools_render", {"prompt": "x", "fail": True, "seconds": 0.2}, mode="auto")
    assert failed["status"] == "error" and failed["error"]["code"] == "job_failed" and "fake render failed" in failed["error"]["detail"]


async def test_running_call_can_be_waited_for_and_cancelled(th):
    r = await th.call("fake_tools_render", {"prompt": "slow", "seconds": 30}, mode="auto", wait=0.5)
    assert r["status"] == "running" and r["job_id"]
    c = (await th.client.post(f"/api/tools/calls/{r['call_id']}/cancel")).json()
    assert c["status"] == "cancelled"
    job = (await th.client.get(f"/api/s/fake-tools/v1/render/{r['job_id']}")).json()
    assert job["state"] == "cancelled"


async def test_tools_source_job_and_file_input(th):
    img = await th.call("fake_tools_make_image", {"prompt": "ref"}, mode="auto")
    oid = img["outputs"][0]["output_id"]
    r = await th.call("fake_tools_paint", {"prompt": "again", "image": {"$file": f"output:{oid}"}, "style": "ink"}, mode="auto")
    assert r["status"] == "done", r
    job = (await th.client.get(f"/api/s/fake-tools/v1/render/{r['result']['id']}")).json()
    assert job["image"] == f"output:{oid}" and job["style"] == "ink"
    bad = await th.call("fake_tools_paint", {"prompt": "x", "image": "output:000000000000"}, mode="auto")
    assert bad["status"] == "error" and bad["error"]["code"] == "unknown_output"


async def test_multipart_file_from_an_output(th):
    img = await th.call("fake_tools_make_image", {"prompt": "mesh-ish"}, mode="auto")
    oid = img["outputs"][0]["output_id"]
    r = await th.call("fake_tools_upload_mesh", {"mesh": f"output:{oid}", "note": "n"}, mode="auto")
    assert r["status"] == "done" and r["result"]["has_glb_name"] and r["result"]["content_type"].startswith("multipart/form-data")


async def test_mod_errors_and_stopped_mods(th):
    r = await th.call("fake_tools_fail", {})
    assert r["status"] == "error" and r["error"]["code"] == "upstream_error" and "fake failure" in r["error"]["detail"]
    r = await th.call("fake_tools_wipe", {"jid": "nope"}, mode="ask")
    res = (await th.client.post(f"/api/approvals/{r['approval_id']}?wait=10", json={"approve": True})).json()
    assert res["status"] == "error" and res["error"]["code"] == "mod_error" and "no job nope" in res["error"]["detail"]


async def test_hub_tools(th):
    r = await th.call("hub_list_services", {})
    assert r["status"] == "done" and r["result"]["services"][0]["id"] == "fake-tools"
    r = await th.call("hub_memory_status", {})
    assert r["status"] == "done" and r["result"]["total_gb"] > 0
    await th.call("fake_tools_make_image", {"prompt": "searchable fox"}, mode="auto")
    r = await th.call("hub_search_outputs", {"q": "fox", "kind": "image"})
    [o] = r["result"]["outputs"]
    assert o["ref"].startswith("output:") and o["prompt"] == "searchable fox"
    d = await th.call("hub_get_output", {"id": o["ref"]})
    assert d["result"]["kind"] == "image" and d["result"]["meta"]["params"]["aspect"] == "1:1" or d["result"]["meta"]
    stop = await th.call("hub_stop_service", {"id": "fake-tools"})
    assert stop["status"] == "needs_approval"
    job = await th.call("fake_tools_render", {"prompt": "s", "seconds": 0.3}, mode="auto", wait=0)
    st = await th.call("hub_job_status", {"call_id": job["call_id"], "wait": 10})
    assert st["result"]["status"] == "done"


async def test_two_pending_approvals_keep_their_own_arguments(th):
    a = await th.call("fake_tools_make_image", {"prompt": "one", "aspect": "1:1"})
    b = await th.call("fake_tools_make_image", {"prompt": "two", "aspect": "9:16"})
    rb, ra = await asyncio.gather(th.client.post(f"/api/approvals/{b['approval_id']}?wait=10", json={"approve": True}),
                                  th.client.post(f"/api/approvals/{a['approval_id']}?wait=10", json={"approve": True}))
    assert ra.json()["result"]["aspect"] == "1:1" and rb.json()["result"]["aspect"] == "9:16"


async def test_approvals_survive_a_hub_restart_and_expire(services_dir, root, make_app, tools_cfg):
    import re

    import httpx

    from utils.tests.conftest import free_port
    from utils.tests.tools.conftest import wait_ready

    services = services_dir("fake-tools")
    toml = services / "fake-tools" / "service.toml"
    toml.write_text(re.sub(r"(?m)^port = \d+", f"port = {free_port()}", toml.read_text()))

    async def hub():
        app = make_app(tools_cfg, port=7000, autostart=True)
        return app

    app = await hub()
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://hub", timeout=30) as c:
            await wait_ready(c, "fake-tools")
            r = (await c.post("/api/tools/fake_tools_make_image/call", json={"arguments": {"prompt": "kept"}})).json()
            old = (await c.post("/api/tools/fake_tools_make_image/call", json={"arguments": {"prompt": "old"}})).json()
            await app.state.hub.db.execute("UPDATE approvals SET created_ts = created_ts - 90000 WHERE id = ?", (old["approval_id"],))
    app = await hub()
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://hub", timeout=30) as c:
            await wait_ready(c, "fake-tools")
            pending = (await c.get("/api/approvals")).json()
            assert [a["id"] for a in pending] == [r["approval_id"]]
            assert (await c.get(f"/api/approvals/{old['approval_id']}")).json()["state"] == "expired"
            res = (await c.post(f"/api/approvals/{r['approval_id']}?wait=10", json={"approve": True})).json()
            assert res["status"] == "done" and res["outputs"][0]["kind"] == "image"


def test_coerce_forgives_small_slips():
    from utils.tools.schema import coerce

    s = {"type": "object", "properties": {"aspect": {"type": "string", "enum": ["1:1 (Square)", "16:9 (Widescreen)"]},
                                          "steps": {"type": "integer"}, "hd": {"type": "boolean"},
                                          "mode": {"type": "string", "enum": ["Fast", "Slow"]}}}
    assert coerce(s, {"aspect": "16:9", "steps": "8", "hd": "true", "mode": "fast"}) == {
        "aspect": "16:9 (Widescreen)", "steps": 8, "hd": True, "mode": "Fast"}
    assert coerce(s, {"aspect": "4:3", "steps": "x"}) == {"aspect": "4:3", "steps": "x"}
    assert coerce(s, {"aspect_ratio": "16:9", "step": 4}) == {"aspect": "16:9 (Widescreen)", "steps": 4}
    assert coerce(s, {"aspect": '"16:9"'}) == {"aspect": "16:9 (Widescreen)"}        # quotes the model added
    assert coerce(s, {"aspect_ratio": "1:1", "aspect": "16:9"}) == {"aspect_ratio": "1:1", "aspect": "16:9 (Widescreen)"}  # no clash


async def test_dry_run_makes_a_stand_in(th):
    r = await th.client.post("/api/tools/fake_tools_make_image/call?wait=10",
                             json={"arguments": {"prompt": "a pretend fox", "aspect": "16:9"}, "mode": "auto", "origin": {"dry_run": True}})
    d = r.json()
    assert d["status"] == "done" and d["result"]["state"] == "done"
    [o] = d["outputs"]
    assert o["kind"] == "image" and o["title"] == "a pretend fox"
    assert not list((th.root / "outputs" / "fake-tools").rglob("*.png"))      # the mod made nothing
    assert len(list((th.root / "outputs" / "eval").rglob("*.png"))) == 1
    meta = (await th.client.get(f"/api/outputs/{o['output_id']}")).json()["meta"]
    assert meta["dry_run"] is True and meta["params"]["aspect"] == "16:9"
    a = (await th.call("fake_tools_say", {"text": "real clip"}, mode="auto"))["outputs"][0]
    r = (await th.client.post("/api/tools/fake_tools_say/call?wait=10", json={"arguments": {"text": "pretend clip"}, "mode": "auto",
                                                                             "origin": {"dry_run": True}})).json()
    assert r["outputs"][0]["kind"] == "audio" and r["outputs"][0]["output_id"] != a["output_id"]
    r = (await th.client.post("/api/tools/fake_tools_get_item/call", json={"arguments": {"item_id": "x"}, "origin": {"dry_run": True}})).json()
    assert r["result"]["id"] == "x"     # reads still run
    # plan 22.4: writes and destructive calls (a mod's and the hub's) are stand-ins: nothing changes
    r = (await th.client.post("/api/tools/hub_start_service/call?wait=10", json={"arguments": {"id": "fake-tools"}, "mode": "auto",
                                                                                  "origin": {"dry_run": True}})).json()
    assert r["status"] == "done" and r["result"]["dry_run"] is True
    r = (await th.client.post("/api/tools/hub_stop_service/call?wait=10", json={"arguments": {"id": "fake-tools"}, "mode": "auto",
                                                                                 "origin": {"dry_run": True}})).json()
    assert r["status"] in ("done", "needs_approval")
    assert th.hub.services.get("fake-tools").state == "ready"


async def test_calls_ask_the_memory_triggers_to_make_room(th):
    """A tool call carries X-GAIFA-Make-Room (agent.make_room), and the memory trigger hook sees it
    whatever its case (it was missed once: a 3D job then failed with needs_room)."""
    seen = []

    async def hook(svc, method, path, headers):
        seen.append(headers.get("x-gaifa-make-room"))

    th.hub.services.before_proxy.append(hook)
    r = await th.call("fake_tools_make_image", {"prompt": "x"}, mode="auto")
    assert r["status"] == "done" and seen == ["1"]


async def test_dry_run_with_nothing_to_stand_in_makes_a_stub(th):
    """With no real audio yet (a fresh install, or after the outputs were cleared), a dry run of a
    speech tool writes a second of silence instead of failing."""
    import wave

    r = (await th.client.post("/api/tools/fake_tools_say/call?wait=10", json={"arguments": {"text": "pretend clip"}, "mode": "auto",
                                                                             "origin": {"dry_run": True}})).json()
    assert r["status"] == "done" and r["outputs"][0]["kind"] == "audio"
    [wav] = (th.root / "outputs" / "eval").rglob("*.wav")
    with wave.open(str(wav)) as w:
        assert w.getnframes() == w.getframerate()


def test_stand_in_stubs_and_links(tmp_path):
    import os
    import struct

    from PIL import Image

    from utils.tools import results

    pic = Image.new("RGB", (64, 36))
    glb = tmp_path / "m.glb"
    assert results._stub("model3d", glb, pic)
    magic, version, length = struct.unpack("<4sII", glb.read_bytes()[:12])
    assert (magic, version, length) == (b"glTF", 2, glb.stat().st_size)
    src, dst = tmp_path / "big.bin", tmp_path / "link.bin"
    src.write_bytes(b"x" * 100)
    results._link(src, dst)
    assert os.stat(src).st_ino == os.stat(dst).st_ino        # a hard link: no second copy
