"""Plan 24.4: view_output on documents (a PDF page reaches the model as an image; a text output
gives its start and points to hub_read_document), and #n refs for the hub's reading tools."""

from __future__ import annotations

import json


def pdf_pages(n: int = 3) -> list[str]:
    return [f"Page {i + 1} text about otters." for i in range(n)]


async def test_a_pdf_page_reaches_the_model_as_an_image(env):
    oid = env.hub.doc("report.pdf", pdf_pages())
    tid = await env.thread(mode="auto")
    env.model.queue({"tool_calls": [{"name": "view_output", "arguments": {"ref": f"output:{oid}", "page": 2}}]},
                    {"text": "Page 2 has a chart."})
    await env.send(tid, "what's on page 2?")
    assert env.hub.page_views == [(oid, 2)]
    res = json.loads(env.payloads(tid, "tool_result")[-1]["content"])
    assert "page 2" in res["note"] and res["subtype"] == "pdf"
    msgs = env.model.received[-1]["messages"]
    img = [m for m in msgs if m["role"] == "user" and isinstance(m["content"], list)]
    assert img and img[-1]["content"][1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert "report.pdf p.2" in img[-1]["content"][0]["text"]


async def test_a_page_without_vision_gives_its_text(env):
    oid = env.hub.doc("report.pdf", pdf_pages())
    tid = await env.thread(mode="auto", model="blind")
    env.model.queue({"tool_calls": [{"name": "view_output", "arguments": {"ref": f"output:{oid}", "page": 3}}]}, {"text": "ok"})
    await env.send(tid, "page 3?")
    content = env.payloads(tid, "tool_result")[-1]["content"]
    assert "can't see images" in content and "Page 3 text about otters." in content and "<untrusted" in content
    assert env.hub.page_views == []


async def test_bad_pages_and_non_pdfs(env):
    pdf = env.hub.doc("report.pdf", pdf_pages())
    md = env.hub.doc("notes.md", text="# Notes\nhello", kind="text", subtype="markdown")
    tid = await env.thread(mode="auto")
    env.model.queue({"tool_calls": [{"name": "view_output", "arguments": {"ref": f"output:{pdf}", "page": 9}},
                                    {"name": "view_output", "arguments": {"ref": f"output:{md}", "page": 1}}]}, {"text": "ok"})
    await env.send(tid, "pages")
    errs = {r["error"]["code"] for r in env.payloads(tid, "tool_result")[-2:]}
    assert errs == {"no_page"}


async def test_a_text_output_points_to_the_read_tool(env):
    long = "# Guide\n" + "\n".join(f"Step {i}: stir the pot." for i in range(400))
    oid = env.hub.doc("guide.md", text=long, kind="text", subtype="markdown")
    tid = await env.thread(mode="auto")
    env.model.queue({"tool_calls": [{"name": "view_output", "arguments": {"ref": f"output:{oid}"}}]}, {"text": "ok"})
    await env.send(tid, "look at it")
    content = env.payloads(tid, "tool_result")[-1]["content"]
    head, body = content.split("\n", 1)
    assert "hub_read_document(ref, offset=2000)" in head and "markdown" in head
    assert body.startswith(f'<untrusted source="output:{oid} guide.md">\n# Guide') and body.endswith("</untrusted>")
    assert len(body) < 2100
    # a short one comes whole
    small = env.hub.doc("tiny.py", text="print('hi')\n", kind="text", subtype="code:python")
    env.model.queue({"tool_calls": [{"name": "view_output", "arguments": {"ref": f"output:{small}"}}]}, {"text": "ok"})
    await env.send(tid, "and this")
    assert "all of it" in env.payloads(tid, "tool_result")[-1]["content"]


async def test_read_tool_results_are_text_and_hash_refs_resolve(env):
    oid = env.hub.doc("report.pdf", pdf_pages())
    tid = await env.thread(mode="auto")
    env.model.queue({"tool_calls": [{"name": "fake_make_image", "arguments": {"prompt": "fox"}}]},
                    {"tool_calls": [{"name": "hub_read_document", "arguments": {"ref": "#1"}},
                                    {"name": "hub_read_document", "arguments": {"ref": f"output:{oid}", "pages": "2"}}]},
                    {"text": "done"})
    await env.send(tid, "read")
    reads = [c for c in env.hub.attempts if c["name"] == "hub_read_document"]
    img = env.payloads(tid, "tool_result")[0]["outputs"][0]["output_id"]
    assert {c["arguments"]["ref"] for c in reads} == {f"output:{img}", f"output:{oid}"}   # #1 became output:<id>
    page = next(r for r in env.payloads(tid, "tool_result") if r["name"] == "hub_read_document" and r["status"] == "done")
    assert page["content"].startswith(f"output:{oid}\n<untrusted") and "Page 2 text" in page["content"]  # text, not escaped JSON
