"""skill-sources 1.2: read_skill reads a skill's other files (`<id>/<path>`), and a body names them."""

from __future__ import annotations


async def test_a_users_skill_files(env, tmp_path):
    d = env.agent.cfg.data / "skills" / "forms"
    (d / "references").mkdir(parents=True)
    (d / "SKILL.md").write_text("---\nname: forms\ndescription: >\n  Fill forms.\n  Use for PDFs.\n---\nRead references/fields.md first.")
    (d / "references" / "fields.md").write_text("Field rules.")
    (d / "logo.png").write_bytes(b"\x89PNG\x00\x00")
    (tmp_path / "secret.md").write_text("secret")
    (d / "out.md").symlink_to(tmp_path / "secret.md")
    s = (await env.client.get("/v1/settings")).json()["skills"]
    assert next(x for x in s if x["id"] == "user/forms")["description"] == "Fill forms. Use for PDFs."
    names = ["forms", "user/forms/references/fields.md", "user/forms/logo.png", "user/forms/out.md", "user/forms/../forms/SKILL.md"]
    env.model.queue({"tool_calls": [{"name": "read_skill", "arguments": {"name": n}} for n in names]}, {"text": "read"})
    tid = await env.thread()
    await env.send(tid, "fill it")
    by = {r["id"]: r for r in env.payloads(tid, "tool_result")}
    body, ref, png, link, dots = (by[c["id"]] for c in env.payloads(tid, "tool_call"))
    assert body["content"].startswith("Read references/fields.md first.")
    assert "read_skill('user/forms/<path>')" in body["content"] and "- references/fields.md" in body["content"]
    assert "out.md" not in body["content"]                       # a symlink out isn't listed
    assert ref["content"] == "Field rules."
    assert png["error"]["code"] == "binary" and link["error"]["code"] == "not_found" and dots["error"]["code"] == "not_found"


async def test_a_mods_skill_files(env):
    env.hub.skills[("fake", "drawing")].update(files=[{"path": "sizes.md", "size": 300}], file_texts={"sizes.md": "1344x768"})
    env.model.queue({"tool_calls": [{"name": "read_skill", "arguments": {"name": n}}
                                    for n in ("fake/drawing", "fake/drawing/sizes.md", "fake/drawing/nope.md")]}, {"text": "ok"})
    tid = await env.thread()
    await env.send(tid, "draw")
    by = {r["id"]: r for r in env.payloads(tid, "tool_result")}
    body, f, nope = (by[c["id"]] for c in env.payloads(tid, "tool_call"))
    assert body["content"].startswith("Use 16:9 for landscapes.") and "- sizes.md (1 KB)" in body["content"]
    assert f["content"] == "1344x768" and nope["error"]["code"] == "not_found"


async def test_the_turning_things_on_skill_loads(env):
    """capability-enablement 4.2: the base harness's skill is listed and read like any other."""
    s = (await env.client.get("/v1/settings")).json()["skills"]
    me = next(x for x in s if x["id"] == "user/turning-things-on")
    assert me["description"].startswith("When something the user asks for is off on this machine")
    env.model.queue({"tool_calls": [{"name": "read_skill", "arguments": {"name": "user/turning-things-on"}}]}, {"text": "ok"})
    tid = await env.thread()
    await env.send(tid, "turn on web search")
    body = env.payloads(tid, "tool_result")[0]["content"]
    assert "hub_setup_plan" in body and "hub_setup_test" in body and "gaifa setup --prompt" in body
