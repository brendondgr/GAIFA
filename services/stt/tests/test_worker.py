"""The model in its own process (the prototype's `isolated.py`): a worker that dies is replaced and the
pass made again, one that hangs is killed, and repeated crashes on the GPU move the model to the CPU.
The scripted mock stands in for the model; the process, the socket and the supervision are real."""

from __future__ import annotations

import asyncio
import os
import signal
import threading
import time

import numpy as np
import pytest

from stt.asr.isolated import IsolatedAsrBackend, WorkerDied, _describe_exit
from stt.asr.registry import build_backend
from stt.config import AsrConfig
from stt.engine import Engine


def speech(seed: int = 0, seconds: float = 0.5) -> np.ndarray:
    return np.random.default_rng(seed).normal(0, 0.1, int(16_000 * seconds)).astype(np.float32)


@pytest.fixture
def isolated():
    made: list[IsolatedAsrBackend] = []

    def build(**kwargs) -> IsolatedAsrBackend:
        backend = IsolatedAsrBackend(AsrConfig(backend="mock", **kwargs.pop("config", {})), **kwargs)
        backend.load()
        made.append(backend)
        return backend

    yield build
    for backend in made:
        backend.unload()


def wait_for_exit(pid: int, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with open(f"/proc/{pid}/stat") as stat:
                if stat.read().rsplit(")", 1)[1].split()[0] == "Z":
                    return True
        except FileNotFoundError:
            return True
        time.sleep(0.05)
    return False


def test_a_worker_answers_and_unloading_ends_it(isolated):
    backend = isolated()
    pid = backend.worker_pid
    assert pid not in (None, os.getpid())
    assert backend.transcribe(speech()).text
    backend.unload()
    assert wait_for_exit(pid)


def test_a_worker_killed_between_passes_is_replaced(isolated):
    backend = isolated()
    notices: list[tuple[str, str]] = []
    backend.set_notice_listener(lambda kind, detail: notices.append((kind, detail)))
    first = backend.worker_pid
    os.kill(first, signal.SIGKILL)
    wait_for_exit(first)

    assert backend.transcribe(speech()).text
    assert backend.worker_pid not in (None, first)
    assert backend.restarts == 1
    assert notices[0][0] == "restarted" and "SIGKILL" in notices[0][1]


def test_a_worker_that_dies_mid_pass_is_replaced_and_the_pass_made_again(isolated):
    backend = isolated()
    first = backend.worker_pid
    os.kill(first, signal.SIGSTOP)
    threading.Timer(0.4, os.kill, (first, signal.SIGKILL)).start()
    assert backend.transcribe(speech()).text
    assert backend.restarts == 1


def test_a_worker_that_stops_answering_is_killed_and_replaced(isolated):
    backend = isolated(hang_base_s=0.5)
    first = backend.worker_pid
    os.kill(first, signal.SIGSTOP)
    started = time.monotonic()
    assert backend.transcribe(speech(seconds=0.1)).text
    assert time.monotonic() - started < 5.0
    assert wait_for_exit(first)


def test_repeated_crashes_on_the_gpu_move_the_model_to_the_cpu(isolated):
    backend = isolated(config={"device": "cuda", "precision": "float16"}, crash_limit=2)
    notices: list[str] = []
    backend.set_notice_listener(lambda kind, _: notices.append(kind))
    for _ in range(2):
        pid = backend.worker_pid
        os.kill(pid, signal.SIGKILL)
        wait_for_exit(pid)
        backend.transcribe(speech())
    assert notices == ["restarted", "fell-back"]
    assert backend.fell_back
    assert (backend._config.device, backend._config.precision) == ("cpu", "int8")


def test_a_second_death_in_one_pass_is_reported_not_looped(isolated, monkeypatch):
    backend = isolated()
    real = backend._request_locked

    def every_pass_dies(message, limit):
        if message[0] == "transcribe":
            raise WorkerDied("gone")
        return real(message, limit)

    monkeypatch.setattr(backend, "_request_locked", every_pass_dies)
    with pytest.raises(WorkerDied):
        backend.transcribe(speech())
    assert backend.restarts == 1


def test_an_abort_is_named_for_what_it_usually_means():
    assert "memory fault" in _describe_exit(-signal.SIGABRT)
    assert _describe_exit(-signal.SIGKILL) == "SIGKILL"


def test_faster_whisper_runs_in_its_own_process():
    config = AsrConfig(backend="faster-whisper", device="cpu", precision="int8")
    assert isinstance(build_backend(config), IsolatedAsrBackend)


def test_the_engine_reports_restarts_and_the_cpu_fallback_in_status(settings, monkeypatch):
    """What `GET /v1/status` shows: the notices from the worker, and the device it ended on."""
    from stt.asr import lifecycle

    monkeypatch.setattr(lifecycle, "build_backend",
                        lambda config: IsolatedAsrBackend(config.model_copy(update={"device": "cuda"}), crash_limit=2))
    engine = Engine(settings, gpu=True)

    async def run():
        await engine.ensure("small")
        try:
            for _ in range(2):
                pid = engine.worker_pid()
                os.kill(pid, signal.SIGKILL)
                wait_for_exit(pid)
                await asyncio.to_thread(engine.transcribe, speech())
            return engine.describe()
        finally:
            await engine.unload()

    state = asyncio.run(run())
    assert state["fell_back"] is True and state["device"] == "cpu" and state["precision"] == "int8"
    assert state["restarts"] == 2
    assert [n["kind"] for n in state["notices"]] == ["restarted", "fell-back"]
