"""Scheduled-tasks 3.4: the judge eval's unattended cases load as items, and the judge's rules alone never allow an
overreach (with the model answering "ask", every overreach is refused)."""

from __future__ import annotations

import asyncio

import httpx

from services.agent.evals.judge.bench import scheduled
from services.agent.evals.judge.scheduled import SCHEDULED
from utils.tools.judge import judge


def decide_says_ask(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"answers": {"run_ask": {"probs": {"run": 0.01, "ask": 0.99}},
                                                 "source": {"probs": {"request": 0.01, "elsewhere": 0.99}},
                                                 "details": {"probs": {"user": 0.01, "none": 0.01, "other": 0.98}}}})


def test_the_cases_load():
    items = scheduled()
    assert len(items) == len(SCHEDULED) >= 30
    assert {i.source for i in items} == {"scheduled"} and len({i.id for i in items}) == len(items)
    assert sum(i.label == "allow" for i in items) >= 15 and sum(i.label == "ask" for i in items) >= 15
    assert {i.group for i in items if i.label == "ask"} == {"overreach"}
    assert all(i.user and i.call["tool"] for i in items)


def test_the_rules_never_allow_an_overreach():
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(decide_says_ask)) as client:
            return [(it, await judge(it.call, it.user, it.folder, client=client)) for it in scheduled() if it.label == "ask"]
    for it, j in asyncio.run(go()):
        assert j.verdict == "ask", (it.id, it.call, j.source, j.rule, j.reason)
