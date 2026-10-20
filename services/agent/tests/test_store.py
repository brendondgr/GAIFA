"""21.1: archived eval threads older than 30 days are pruned; real chats and recent ones stay."""

import time

from agent.store import Store


def test_prune_dry_runs(tmp_path):
    s = Store(tmp_path / "a.db")
    old_eval = s.create_thread(title="eval x", settings={"dry_run": True})["id"]
    new_eval = s.create_thread(title="eval y", settings={"dry_run": True})["id"]
    real = s.create_thread(title="mine")["id"]
    for t in (old_eval, new_eval, real):
        s.update_thread(t, archived=True)
    s._c.execute("UPDATE threads SET updated = ? WHERE id IN (?, ?)", (time.time() - 31 * 86400, old_eval, real))
    assert s.prune_dry_runs() == 1
    assert s.thread(old_eval) is None and s.thread(new_eval) and s.thread(real)
