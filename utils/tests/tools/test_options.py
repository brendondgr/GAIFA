"""20.1: `x-options` on enum parameters: defaults that follow the inputs, refusals with a fix that
names the choices that fit, dependent values, the model's text, `gaifa check`, the MCP form, a mod's
own fix, and the hint to call a sibling tool."""

from __future__ import annotations

import copy

from utils.tests.fixtures.mods import _fakemod
from utils.tools import options
from utils.tools.mcp_approval import form_schema

SHAPE = _fakemod.SHAPE


def test_defaults_follow_the_inputs():
    args, filled = options.fill_defaults(SHAPE, {"prompt": "a fox"})
    assert args["engine"] == "words" and filled == ["engine"]
    args, filled = options.fill_defaults(SHAPE, {"image": "output:abc", "prompt": "x"})
    assert args["engine"] == "picture" and "preset" not in args           # no preset: full quality
    args, filled = options.fill_defaults(SHAPE, {"image": "output:abc", "engine": "body"})
    assert args["engine"] == "body" and filled == []                      # an explicit choice stays


def test_a_choice_that_does_not_fit_is_refused_with_the_ones_that_do():
    [p] = options.problems(SHAPE, {"engine": "words", "image": "output:abc", "prompt": "x"})
    assert p["field"] == "engine" and "can't use `image`" in p["detail"]
    assert "picture (From a picture): objects" in p["fix"] and "body (Body): a person's body" in p["fix"]
    [p] = options.problems(SHAPE, {"engine": "picture", "prompt": "a fox"})
    assert "needs `image`" in p["detail"] and "words (From words)" in p["fix"] and "add `image` to keep picture" in p["fix"]
    assert options.problems(SHAPE, {"engine": "picture", "image": "output:abc"}) == []


def test_dependent_values_follow_their_parent():
    assert options.choices(SHAPE, "preset", {"engine": "body"}) == ["base"]
    assert options.choices(SHAPE, "preset", {"engine": "words"}) == ["base", "fast", "draft"]
    [p] = options.problems(SHAPE, {"engine": "body", "image": "output:abc", "preset": "fast"})
    assert p["field"] == "preset" and p["fix"] == "use one of: base"
    assert options.choices(SHAPE, "engine", {"image": "output:abc"}) == ["picture", "body"]


def test_the_model_reads_the_choices_as_text():
    m = options.for_model(SHAPE)
    eng, pre = m["properties"]["engine"], m["properties"]["preset"]
    assert "x-options" not in eng and "x-depends-on" not in pre and m["properties"]["prompt"] == SHAPE["properties"]["prompt"]
    assert "- words (From words): text only; needs `prompt`; not with `image`; the default with `prompt` and without `image`" in eng["description"]
    assert "- picture (From a picture): objects; needs `image`; preset: base, fast; the default with `image`" in eng["description"]
    assert "depends on `engine`" in pre["description"] and "- fast: fast quality; only when the user asks for a quick result" in pre["description"]
    assert "x-options" in SHAPE["properties"]["engine"]                   # the original is untouched


def test_check_finds_mistakes_in_a_declaration():
    assert options.spec_problems(SHAPE) == []
    bad = copy.deepcopy(SHAPE)
    o = bad["properties"]["engine"]["x-options"]
    o["body"]["default"] = True                                           # two defaults for a picture
    o["ghost"] = {"needs": ["nothing"]}
    found = " | ".join(options.spec_problems(bad))
    assert "'ghost', which isn't in its enum" in found and "'nothing', which isn't a parameter" in found
    assert "2 defaults (picture, body) fit when image" in found


def test_the_mcp_form_lists_only_the_choices_that_fit():
    f = form_schema(SHAPE, ["engine", "preset"], {"image": "output:abc", "engine": "picture"})
    assert f["properties"]["engine"]["enum"] == ["picture", "body"]
    assert f["properties"]["engine"]["enumNames"] == ["From a picture", "Body"]
    assert f["properties"]["preset"]["enum"] == ["base", "fast"]


async def test_the_hub_fills_checks_and_tells_the_model(th):
    r = await th.call("fake_tools_shape", {"image": "output:000000000000"})
    assert r["status"] == "needs_approval" and r["arguments"]["engine"] == "picture" and r["filled"] == ["engine"]
    r = await th.call("fake_tools_shape", {"prompt": "a fox", "engine": "picture"})
    assert r["status"] == "error" and r["error"]["code"] == "invalid_arguments" and "words (From words)" in r["error"]["fix"]
    r = await th.call("fake_tools_shape", {"prompt": "a fox"}, mode="auto")
    assert r["status"] == "done" and r["result"]["ran"]["engine"] == "words"
    tools = (await th.client.get("/api/tools?names=fake_tools_shape&view=model")).json()
    assert "x-options" not in tools[0]["parameters"]["properties"]["engine"]
    full = (await th.client.get("/api/tools?names=fake_tools_shape")).json()
    assert "x-options" in full[0]["parameters"]["properties"]["engine"]


async def test_a_card_edit_that_does_not_fit_stays_pending(th):
    r = await th.call("fake_tools_shape", {"image": "output:000000000000"})
    bad = await th.client.post(f"/api/approvals/{r['approval_id']}", json={"approve": True, "arguments": {"engine": "words", "image": "output:000000000000"}})
    assert bad.status_code == 422 and "can't use `image`" in bad.text
    assert (await th.client.get(f"/api/approvals/{r['approval_id']}")).json()["state"] == "pending"


async def test_a_mods_own_fix_reaches_the_model(th):
    r = await th.call("fake_tools_strict", {})
    assert r["status"] == "error" and r["error"]["code"] == "mod_error"
    assert "plain background" in r["error"]["detail"] and r["error"]["fix"] == "run remove_background on it first"


async def test_a_value_of_a_sibling_tool_says_to_call_that_tool(th):
    r = await th.call("fake_tools_paint", {"prompt": "x", "style": "pencil"})
    assert r["error"]["code"] == "invalid_arguments"
    assert "'pencil' is a style of fake_tools_sketch, not of fake_tools_paint: call fake_tools_sketch instead" in r["error"]["fix"]


async def test_check_reports_the_tools(th):
    rep = (await th.client.get("/api/services/fake-tools/check")).json()
    tools = next(c for c in rep["checks"] if c["name"] == "tools")
    assert tools["status"] == "ok", tools
