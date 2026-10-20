"""22.2: the four hook verbs in the tool loop, an invalid hooks file, and no hooks."""

from __future__ import annotations

from agent.harness import Harness
from agent.hooks import Hooks, problems

HOOKS = """
[[hook]]
verb = "cap"
tool = "fake_get"
per_turn = 1
fix = "use what you found"

[[hook]]
verb = "require_first"
tool = "fake_make_image"
first = "view_output"
when = "image"

[[hook]]
verb = "hint_after_error"
tool = "fake_fail"
text = "fake_fail always fails: don't retry it."

[[hook]]
verb = "trim"
tool = "fake_get"
max_tokens = 5
"""


def test_problems_and_the_verbs():
    import tomllib
    data = tomllib.loads(HOOKS)
    assert problems(data, {"fake_get", "fake_make_image", "fake_fail", "view_output"}) == []
    assert problems({"hook": [{"verb": "cap", "tool": "x"}]}, None) == ["hook 1 (cap): needs per_turn"]
    hk = Hooks(data)
    assert hk.before("fake_get", {}, []) is None and hk.before("fake_get", {}, ["fake_get"])["code"] == "hook_cap"
    assert hk.before("fake_make_image", {"prompt": "x"}, []) is None                      # `when`: only with a picture
    assert hk.before("fake_make_image", {"image": "output:a"}, [])["code"] == "hook_require_first"
    assert hk.before("fake_make_image", {"image": "output:a"}, ["view_output"]) is None
    assert hk.after("fake_fail", "error", "upstream_error") == ("fake_fail always fails: don't retry it.", None)
    assert hk.after("fake_get", "done", None) == (None, 5)
    assert Hooks(None).before("anything", {}, []) is None


async def test_hooks_in_the_loop(env):
    Harness(env.agent.cfg.data).create({"hooks.toml": HOOKS}, activate=True)
    env.model.queue({"tool_calls": [{"name": "fake_get", "arguments": {"id": "a"}}, {"name": "fake_fail", "arguments": {}}]},
                    {"tool_calls": [{"name": "fake_get", "arguments": {"id": "b"}}]}, {"text": "done"})
    tid = await env.thread(settings={"pinned": ["fake"]})
    await env.send(tid, "go")
    res = {r["id"]: r for r in env.payloads(tid, "tool_result")}
    contents = [r["content"] for r in res.values()]
    assert any("trimmed by a harness hook" in c for c in contents)
    assert any("Note: fake_fail always fails" in c for c in contents)
    assert any(r.get("error", {}).get("code") == "hook_cap" for r in res.values())
    assert any(n["text"].startswith("hook:") for n in env.payloads(tid, "note"))
