"""Plan 24.8: what learns from chats doesn't read documents. The miner and the learner's transcript
builder run over chats with an inline document, a document card and a fetched web page; none of
their text shows up in what they produce. Free-text card fields are never inferred."""

from __future__ import annotations

import json

from agent.learn import loop as learn
from agent.learn import mine
from agent.learn import replay

DOC = "Clause 9: the PIN for the vault is AMBER-FALCON-7731."
PAGE = "Breaking: ZEBRA-4410 merger announced (fetched page text)."
SECRETS = ("AMBER-FALCON-7731", "ZEBRA-4410", "Clause 9")


def chat(store, title: str) -> str:
    tid = store.create_thread(title=title)["id"]
    store.append(tid, "user", {"text": "summarize the contract and the news", "attachments": ["a" * 12, "b" * 12], "docs": [
        {"ref": "#1", "id": "a" * 12, "name": "contract.md", "kind": "text", "subtype": "markdown", "tokens": 20, "pages": 0, "lines": 1,
         "outline": [{"level": 1, "title": "Clause 9", "line": 1}], "inline": True, "text": DOC},
        {"ref": "#2", "id": "b" * 12, "name": "annex.pdf", "kind": "document", "subtype": "pdf", "tokens": 9000, "pages": 12, "lines": 400,
         "outline": [], "inline": False}]})
    store.append(tid, "tool_call", {"id": "c1", "name": "hub_read_document", "arguments": {"ref": "#2", "pages": "3"}, "step": "s1"})
    store.append(tid, "tool_result", {"id": "c1", "name": "hub_read_document", "status": "done",
                                      "content": f'<untrusted source="#2 annex.pdf">\n{DOC}\n</untrusted>'})
    store.append(tid, "tool_call", {"id": "c2", "name": "web_fetch", "arguments": {"url": "https://news.example/x"}, "step": "s1"})
    store.append(tid, "tool_result", {"id": "c2", "name": "web_fetch", "status": "done", "content": f'<untrusted source="news.example">\n{PAGE}\n</untrusted>'})
    store.append(tid, "assistant", {"text": "The contract has one clause about access; the news is about a merger.", "step": "s2"})
    return tid


async def test_the_learners_transcripts_show_document_cards_only(env):
    store = env.agent.store
    tid = chat(store, "private docs")
    text = learn.render(store.events(tid))
    assert "(document #1: contract.md, 1 lines)" in text and "(document #2: annex.pdf, 12 pages)" in text
    assert "CALL hub_read_document" in text and "→ done" in text
    assert not any(s in text for s in SECRETS), text
    rec = replay.record(store.events(tid), tid)
    assert not any(s in json.dumps(rec.__dict__) for s in SECRETS)


async def test_the_miner_never_proposes_document_or_free_text(env):
    store = env.agent.store
    t1, t2 = chat(store, "one"), chat(store, "two")
    approvals = [{"id": f"ap_{i}", "tool": "fake_make_image", "state": "approved", "edited": ["prompt", "aspect"],
                  "final": {"prompt": f"draw {DOC}", "aspect": "16:9"}, "origin": {"thread": t}} for i, t in enumerate((t1, t2, t1))]

    async def fake_approvals(state="all", limit=1000):
        return approvals
    env.agent.hub.approvals = fake_approvals
    for t in (t1, t2):           # the same question answered the same way, and a thumbs up, in both chats
        store.append(t, "answer", {"id": "q", "answers": {"Which style?": "Ink"}})
        store.append(t, "feedback", {"value": "up", "output_id": "o" + t})
    done = await mine.run(env.agent.hub, store)
    made = json.dumps(done["proposed"]) + json.dumps(env.hub.prefs)
    assert [(p.get("field"), p.get("value")) for p in done["proposed"] if p.get("tool")] == [("aspect", "16:9")]   # not the prompt
    assert not any(s in made for s in SECRETS), made
    assert all(p.get("field") not in mine.FREE_TEXT for p in done["proposed"])
