"""The model in a spawned worker: load, ask, unload ends the process; a crash answers worker_died and the next
call starts a new worker."""

from __future__ import annotations

import functools
import os
import signal

import pytest

from decide.engine import Decider, LocalBackend
from decide.models.fake import FakeModel
from decide.worker import WorkerBackend, WorkerDied

Q = [{"id": "q", "type": "yesno", "question": "tests? [yes_if: tests]"}]


@pytest.fixture
def worker(settings):
    w = WorkerBackend(functools.partial(LocalBackend, {"fake": FakeModel}, settings.models_dir), timeout_s=30)
    yield w
    w.unload()


def test_ask_in_a_worker_and_unload_ends_it(worker, settings):
    d = Decider(worker, settings.state_dir)
    answers, ms = d.ask("fake", "run the tests", Q)
    assert answers["q"]["top"] == "yes" and ms >= 0
    pid = worker.proc.pid
    assert d.unload() is True and worker.proc is None
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_refusal_comes_back_from_the_worker(worker, settings):
    (settings.models_dir / "fake" / "revision").write_text("2" * 40)
    with pytest.raises(PermissionError):
        worker.load("fake")
    assert worker.proc is None


def test_crash_then_a_new_worker(worker, settings):
    d = Decider(worker, settings.state_dir)
    d.ask("fake", "x", Q)
    os.kill(worker.proc.pid, signal.SIGKILL)
    with pytest.raises(WorkerDied):
        d.ask("fake", "x", Q)
    assert d.loaded is False
    answers, _ = d.ask("fake", "tests", Q)
    assert answers["q"]["top"] == "yes"
