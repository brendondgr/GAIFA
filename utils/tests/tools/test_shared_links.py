"""Links the user typed are read directly: web_fetch of a URL in `origin.links` (the http(s) links of the user's own
messages, sent by the agent) runs without a card in every mode but Plan; only that exact URL after trivial
normalisation, never one the judge's URL rules flag; the links and the question are never stored. Against fake-perms
installed as the `web` mod (test_searched.py's fixture)."""

from __future__ import annotations

import json

import pytest

from utils.tests.tools.test_searched import FETCH, web  # noqa: F401: the fixture
from utils.tools import searched, webread
from utils.tools.approvals import MODES, decide

LINKS = ["https://Example.org/guide#part", "https://docs.example.com/a?b=1", "https://example.org/login?token=abc123"]


def test_shared_matches_exactly_after_normalising():
    assert searched.shared("https://example.org/guide", LINKS)
    assert searched.shared("HTTPS://EXAMPLE.ORG:443/guide#x", LINKS)
    assert searched.shared("https://docs.example.com/a?b=1", LINKS)
    for url in ("https://example.org/guide/more", "https://example.org/guid", "https://docs.example.com/a",
                "https://docs.example.com/a?b=1&c=2", "http://example.org/guide", "https://example.org.evil.com/guide",
                "https://example.org/login?token=abc123"):        # the last carries credentials: the URL rules flag it
        assert not searched.shared(url, LINKS), url
    assert not searched.shared("https://example.org/guide", None)
    assert not searched.shared("https://example.org/guide", "https://example.org/guide")    # a list only
    assert not searched.shared(None, LINKS)


@pytest.mark.parametrize("mode", MODES)
def test_decide_runs_a_shared_link_except_in_plan(mode):
    from utils import config

    c = config.Config()
    verdict, why = decide("web_fetch", "network", c, mode, shared=True)
    assert verdict == ("deny" if mode == "plan" else "allow") and (mode == "plan" or why == "a link you shared")
    c.agent.permissions.ask = ["web_fetch"]
    assert decide("web_fetch", "network", c, mode, shared=True)[0] == ("deny" if mode == "plan" else "ask")


async def test_a_link_the_user_typed_runs_without_a_card(web):  # noqa: F811
    r = await web.call(FETCH, {"url": "https://example.org/guide"}, thread="t1", turn=3, service="agent",
                       links=LINKS, question="What does the guide say about gaiters?")
    assert r["status"] == "done" and not r.get("approval_id"), r
    row = await web.hub.db.fetchone("SELECT origin FROM tool_calls WHERE id = ?", (r["call_id"],))
    origin = json.loads(row["origin"])
    assert origin.get("shared_link") is True
    assert "links" not in origin and "question" not in origin and "gaiters" not in row["origin"]   # never stored
    assert webread.question_for({"thread": "t1", "turn": 3}) == "What does the guide say about gaiters?"


@pytest.mark.parametrize("url, extra", [
    ("https://example.org/other", {"links": LINKS}),                       # not one the user typed
    ("https://example.org/login?token=abc123", {"links": LINKS}),          # typed, but the URL rules flag it
    ("https://example.org/guide", {}),                                     # no links sent (MCP, another client)
    ("https://example.org/guide", {"links": "https://example.org/guide"}), # not a list
])
async def test_anything_else_still_asks(web, url, extra):  # noqa: F811
    r = await web.call(FETCH, {"url": url}, thread="t1", **extra)
    assert r["status"] == "needs_approval", (url, extra, r)
    a = await web.hub.db.fetchone("SELECT origin FROM approvals WHERE id = ?", (r["approval_id"],))
    assert "links" not in json.loads(a["origin"])


async def test_plan_mode_refuses_it(web):  # noqa: F811
    r = await web.call(FETCH, {"url": "https://example.org/guide"}, mode="plan", thread="t1", links=LINKS)
    assert r["status"] == "denied"


def test_private_out_drops_the_users_words():
    o = {"thread": "t", "said": ["hi"], "question": "q", "links": ["https://a.org/"], "turn": 1}
    assert webread.private_out(o) == {"thread": "t", "turn": 1}
    same = {"thread": "t"}
    assert webread.private_out(same) is same and webread.private_out(None) is None
