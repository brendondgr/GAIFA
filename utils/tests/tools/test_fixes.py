"""46.5: fixes and log lines on a failed call: per error code, out of memory, the log excerpt, and through a real call."""

from __future__ import annotations

from utils.tools.catalog import ToolDef
from utils.tools.fixes import fixes_for, lighter_preset, log_excerpt


def tool(preset_enum=None) -> ToolDef:
    props = {"prompt": {"type": "string"}}
    if preset_enum:
        props["preset"] = {"type": "string", "enum": preset_enum}
    return ToolDef("gen3d_make_3d", "gen3d", "make_3d", "", {"type": "object", "properties": props}, risk="generate")


def kinds(fx):
    return [f["label"] for f in fx]


def test_a_mod_that_explained_it_gets_no_restart():
    # seen 2026-10-25 (chat t_380bd8fbc0ec): a site's HTTP 403 offered "Restart Web" and "Retry"
    t = tool()
    err = {"code": "upstream_error", "detail": "Web failed (HTTP 502): https://x/ answered HTTP 403", "fix": "try another source"}
    assert fixes_for(t, {}, err, "Web", []) == []
    assert kinds(fixes_for(t, {}, {**err, "fix": "check the mod's Logs tab; try again or change the inputs"}, "Web", [])) == ["Restart Web", "Retry"]
    assert kinds(fixes_for(t, {}, {"code": "upstream_error", "detail": "x"}, "Web", [])) == ["Restart Web", "Retry"]
    assert "Free the GPU" in kinds(fixes_for(t, {}, {**err, "detail": "CUDA error: out of memory"}, "Web", []))


def test_each_code_gets_its_fix():
    t = tool()
    assert kinds(fixes_for(t, {}, {"code": "service_not_running", "detail": "x"}, "3D Generate", [])) == ["Start 3D Generate", "Retry"]
    assert fixes_for(t, {}, {"code": "service_not_running"}, "3D", [])[0] == {"label": "Start 3D", "tool": "hub_start_service", "arguments": {"id": "gen3d"}}
    assert kinds(fixes_for(t, {}, {"code": "needs_room"}, "3D", [])) == ["Free the GPU", "Retry"]
    assert fixes_for(t, {}, {"code": "mod_error"}, "3D", [])[0] == {"label": "Restart 3D", "service": "gen3d", "action": "restart"}
    assert kinds(fixes_for(t, {}, {"code": "tool_unavailable"}, "3D", [])) == ["Set it up: gaifa setup gen3d"]
    for code in ("invalid_arguments", "unknown_tool", "denied"):
        assert fixes_for(t, {}, {"code": code}, "3D", []) == []


def test_out_of_memory_offers_freeing_and_a_lighter_preset():
    t = tool(["quality", "balanced", "fast"])
    fx = fixes_for(t, {"preset": "quality"}, {"code": "job_failed", "detail": "the job failed"}, "3D", ["torch.OutOfMemoryError: HIP out of memory"])
    assert kinds(fx) == ["Free the GPU", "Retry with the fast preset", "Retry"]
    assert fx[1]["retry"] == {"preset": "fast"}
    assert lighter_preset(t, "fast") is None and lighter_preset(tool(), None) is None


def test_log_excerpt_keeps_the_lines_that_name_the_error():
    lines = [{"text": f"step {i}"} for i in range(30)] + [{"text": "loading weights"}, {"text": "Traceback (most recent call last):"}, {"text": "RuntimeError: boom"}]
    assert log_excerpt(lines) == ["loading weights", "Traceback (most recent call last):", "RuntimeError: boom"]
    assert log_excerpt([{"text": "a"}, {"text": "b"}]) == ["a", "b"]


async def test_a_failed_job_carries_its_fixes(th):
    r = await th.call("fake_tools_render", {"prompt": "x", "fail": True, "seconds": 0.2}, mode="auto")
    err = r["error"]
    assert err["code"] == "job_failed" and err["fixes"][-1] == {"label": "Retry", "retry": {}}
    assert isinstance(err.get("log", []), list)
