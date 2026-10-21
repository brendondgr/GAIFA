"""Hidden outputs (plan 30.9: the web mod's saved pages) aren't the user's: the library never indexes them, and
drops one it had indexed once it is hidden (on the next reconcile or its `output` event)."""

from __future__ import annotations

import json

from embed.search import index_scope
from tests.conftest import png
from tests.test_library import make, run


def test_reconcile_skips_hidden_and_drops_ones_indexed_before(settings, hub):
    hub.add("mine", "image", png("a dog"), title="dog")
    hub.add("page", "text", text="the 15 best things to do", title="Things to do", hidden=True)
    lib = make(settings, hub)
    assert run(lib.reconcile())["queued"] == 1
    run(lib.drain())
    assert lib.store.get("page") is None and lib.store.get("mine")["state"] == "done"
    # a page indexed by an older version, before pages were hidden: the next reconcile drops it and its chunks
    rec = dict(hub.outputs["page"][0])
    rec.pop("hidden")
    lib.store.queue(rec, "old")
    run(lib.drain())
    assert lib.store.chunks_of("page")
    out = run(lib.reconcile())
    assert out["removed"] == 1 and lib.store.get("page") is None and lib.store.chunks_of("page") == []
    # even from a hub that lists hidden outputs, they're skipped
    hub.outputs["page"][0]["hidden"] = True
    lib.hub.outputs = lambda page=500: _all(hub)
    assert run(lib.reconcile())["queued"] == 0 and lib.store.get("page") is None


async def _all(hub):
    for rec, _ in hub.outputs.values():
        yield rec


def test_an_event_for_a_hidden_output_never_queues_it_and_drops_it(settings, hub):
    hub.add("p", "text", text="a saved page", title="Page")
    lib = make(settings, hub)
    run(lib.reconcile())
    run(lib.drain())
    assert lib.store.get("p")["state"] == "done"
    rec = {**hub.outputs["p"][0], "hidden": True}
    run(lib.on_event({"type": "output", "output": rec}))
    assert lib.store.get("p") is None and lib.store.chunks_of("p") == [] and lib.store.counts()["pending"] == 0
    run(lib.on_event({"type": "output", "output": {**rec, "id": "q"}}))
    assert lib.store.get("q") is None


def test_a_scoped_search_doesnt_index_an_attached_hidden_page(settings, hub):
    hub.add("page", "text", text="ferry fares", title="Ferry fares", hidden=True)
    hub.add("doc", "text", text="my notes", title="Notes")
    lib = make(settings, hub)
    assert run(index_scope(lib, {"page", "doc"})) == 0
    assert lib.store.get("page") is None and lib.store.get("doc")["state"] == "done"
    assert json.dumps(lib.status())                                  # still a plain status
