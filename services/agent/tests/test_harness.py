"""22.1: the harness as versioned files: the base in git, learned versions as overlays, validation,
pinning, activate and rollback; with no overlay the system prompt is byte-identical to before."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent import prompts
from agent.harness import Harness, HarnessError, validate

OLD = (Path(__file__).parent / "fixtures" / "base-prompt-2026-11-15.txt").read_text()   # capability-enablement 2.2


def test_the_base_prompt_is_unchanged():
    assert prompts.base_text() == OLD
    assert prompts.build({"base": Harness("/nonexistent").tree(0)["systemprompt.md"]}) == prompts.build({}) == OLD


def test_the_active_version_carries_the_off_rules(tmp_path):
    """capability-enablement 2.2: the rule for what's off reaches a learned version that doesn't change the prompt."""
    h = Harness(tmp_path)
    h.create({"guardrails.md": "- Never invent ids.\n"}, activate=True)
    sp = h.tree()["systemprompt.md"]
    assert 'Needs something under "Off on this machine"? Not set up: say in one sentence what is missing' in sp
    assert "A `capability_unavailable` result is final for this turn unless you turn the mod on." in sp
    assert "when `web_search` is among your tools, search with it" in sp


def test_versions_overlay_activate_and_roll_back(tmp_path):
    h = Harness(tmp_path)
    assert h.current() == 0 and "systemprompt.md" in h.tree()
    n1 = h.create({"tools/gen3d_make_3d.md": "Send stages as a list.\n"}, notes="kept -> note -> 2 errors", activate=True)
    assert h.current() == n1 == 1 and h.tree()["tools/gen3d_make_3d.md"].startswith("Send")
    n2 = h.create({"guardrails.md": "- Never invent ids.\n"}, removed=["tools/gen3d_make_3d.md"])
    assert h.current() == 1 and "tools/gen3d_make_3d.md" not in h.tree(n2) and h.tree(n2)["guardrails.md"]
    assert "+- Never invent ids." in h.diff(1, 2) and "-Send stages" in h.diff(1, 2)
    h.activate(2)
    assert h.current() == 2
    h.activate(0)                                            # rollback to the base
    assert h.current() == 0 and "guardrails.md" not in h.tree() or not h.tree().get("guardrails.md", "").strip()
    assert [v["n"] for v in h.versions()] == [0, 1, 2] and h.versions()[0]["active"]
    with pytest.raises(HarnessError):
        h.activate(9)


def test_validation_refuses_a_broken_harness(tmp_path):
    h = Harness(tmp_path)
    with pytest.raises(HarnessError, match="always-on"):
        h.create({"guardrails.md": "x" * 30000})
    with pytest.raises(HarnessError, match="frontmatter"):
        h.create({"skills/my-way/SKILL.md": "no frontmatter"})
    with pytest.raises(HarnessError, match="not a harness file"):
        h.create({"secret.py": "print(1)"})
    assert any("no tool" in p for p in validate({"systemprompt.md": "x", "tools/nope.md": "y"}, {"real_tool"}))
    assert any("template" in p for p in validate({"systemprompt.md": "hi {{ name }}"}))
    assert any("unknown verb" in p for p in validate({"systemprompt.md": "x", "hooks.toml": '[[hook]]\nverb = "exec"\ntool = "x"\n'}))


async def test_a_chat_can_pin_a_version_and_turns_record_it(env):
    from agent.harness import Harness
    h = Harness(env.agent.cfg.data)
    n = h.create({"guardrails.md": "- Always answer in one sentence.\n"})
    env.model.queue({"text": "ok"}, {"text": "ok"})
    tid = await env.thread(settings={"harness": n})
    await env.send(tid, "hi")
    sys_prompt = env.model.received[-1]["messages"][0]["content"]
    assert "## Guardrails\n- Always answer in one sentence." in sys_prompt
    assert env.payloads(tid, "usage")[-1]["harness"] == n
    plain = await env.thread()
    await env.send(plain, "hi")
    assert "Always answer in one sentence" not in env.model.received[-1]["messages"][0]["content"]   # the active version is still 0
    r = await env.client.post(f"/v1/harness/versions/{n}/activate")
    assert r.json() == {"current": n}
    assert "+- Always answer" in (await env.client.get(f"/v1/harness/versions/{n}/diff")).json()["diff"]


async def test_harness_skills_and_tool_notes_reach_the_model(env):
    from agent.harness import Harness
    h = Harness(env.agent.cfg.data)
    h.create({"skills/house-style/SKILL.md": "---\nname: house-style\ndescription: How this user likes pictures\n---\nWarm light.\n",
              "tools/fake_get.md": "Ids are lowercase."}, activate=True)
    env.model.queue({"tool_calls": [{"name": "read_skill", "arguments": {"name": "house-style"}}]}, {"text": "ok"})
    tid = await env.thread(settings={"pinned": ["fake"]})
    await env.send(tid, "hi")
    assert "- user/house-style: How this user likes pictures" in env.model.received[0]["messages"][0]["content"]
    assert env.payloads(tid, "tool_result")[-1]["content"].strip() == "Warm light."
    fn = next(t for t in env.model.received[-1]["tools"] if t["function"]["name"] == "fake_get")
    assert fn["function"]["description"].endswith("Ids are lowercase.")


def test_tool_notes_must_agree_with_todays_schema():
    """22.8: the first live run adopted notes that said gen3d_make_3d needs `image` and that
    comfy_generate_image takes `workflow_id`; both contradicted the tools' schemas."""
    schemas = {"gen3d_make_3d": {"properties": {"prompt": {}, "image": {}, "engine": {}}, "required": []},
               "comfy_generate_image": {"properties": {"prompt": {}, "workflow": {}}, "required": ["prompt"]}}
    tree = {"systemprompt.md": "x",
            "tools/gen3d_make_3d.md": "**Required parameter**: `image` - without it the call fails.",
            "tools/comfy_generate_image.md": 'Correct call: `comfy_generate_image {"prompt": "a cat", "workflow_id": "z"}`'}
    found = " | ".join(validate(tree, schemas))
    assert "says `image` is required" in found and "workflow_id, which the tool doesn't take" in found
    ok = {"systemprompt.md": "x", "tools/comfy_generate_image.md": 'Example: {"prompt": "a cat", "workflow": "z"}; `prompt` is required.'}
    assert validate(ok, schemas) == []
