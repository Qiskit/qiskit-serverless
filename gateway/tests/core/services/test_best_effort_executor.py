"""Tests for the shared best-effort executor. Real threads, synchronised with events and timeouts."""

import threading

import pytest

from core.services.best_effort_executor import shutdown_best_effort_executor, submit_best_effort

WAIT = 5


@pytest.fixture(name="small_pool", autouse=True)
def small_pool_fixture(settings):
    settings.BEST_EFFORT_MAX_WORKERS = 2
    settings.BEST_EFFORT_MAX_PENDING = 2
    shutdown_best_effort_executor()
    yield
    shutdown_best_effort_executor()


def test_the_task_runs_on_another_thread():
    done = threading.Event()
    seen = []

    def task():
        seen.append(threading.current_thread())
        done.set()

    assert submit_best_effort(task) is True
    assert done.wait(WAIT)
    assert seen[0] is not threading.current_thread()


def test_a_full_pool_drops_the_next_task():
    release = threading.Event()
    started = threading.Barrier(3)
    ran = []

    def blocker():
        started.wait(WAIT)
        release.wait(WAIT)

    assert submit_best_effort(blocker) is True
    assert submit_best_effort(blocker) is True
    started.wait(WAIT)

    assert submit_best_effort(lambda: ran.append(1)) is False

    release.set()
    shutdown_best_effort_executor()
    assert not ran


def test_a_failing_task_does_not_propagate_and_frees_its_slot():
    done = threading.Event()

    def failing():
        try:
            raise RuntimeError("boom")
        finally:
            done.set()

    for _ in range(5):  # more submissions than MAX_PENDING: only possible if every slot is released
        done.clear()
        assert submit_best_effort(failing) is True
        assert done.wait(WAIT)
        shutdown_best_effort_executor()


def test_submit_works_again_after_a_shutdown():
    shutdown_best_effort_executor()
    shutdown_best_effort_executor()  # safe twice
    done = threading.Event()

    assert submit_best_effort(done.set) is True
    assert done.wait(WAIT)
