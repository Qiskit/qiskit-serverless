"""Tests for the shared best-effort executor. Real threads, synchronised with events and timeouts."""

import logging
import threading
import time

import pytest

from core.services.best_effort_executor import _State, shutdown_best_effort_executor, submit_best_effort

WAIT = 5


@pytest.fixture(name="small_pool", autouse=True)
def small_pool_fixture(settings):
    settings.BEST_EFFORT_MAX_WORKERS = 2
    settings.BEST_EFFORT_MAX_PENDING = 2
    shutdown_best_effort_executor()
    yield
    _State.closing = False
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


def _submit_until_accepted(fn):
    """The wrapper frees its slot just after the task ends, so a submit right after may still see a full pool."""
    deadline = time.monotonic() + WAIT
    while time.monotonic() < deadline:
        if submit_best_effort(fn):
            return True
        time.sleep(0.05)
    return False


def test_a_failing_task_does_not_propagate_and_frees_its_slot(caplog):
    finished = threading.Barrier(3)

    def failing():
        try:
            raise RuntimeError("boom")
        finally:
            finished.wait(WAIT)

    with caplog.at_level(logging.WARNING, logger="gateway.best_effort"):
        assert submit_best_effort(failing) is True
        assert submit_best_effort(failing) is True
        finished.wait(WAIT)

        assert _submit_until_accepted(lambda: None) is True

    assert "failing" in caplog.text and "boom" in caplog.text


def test_queued_tasks_are_skipped_once_the_interpreter_is_closing():
    ran = []
    _State.closing = True

    assert submit_best_effort(lambda: ran.append(1)) is True
    assert submit_best_effort(lambda: ran.append(2)) is True  # MAX_PENDING is 2: the pool is now full

    assert _submit_until_accepted(lambda: None) is True  # only possible if the skipped tasks released their slots
    assert not ran


def test_submit_works_again_after_a_shutdown():
    shutdown_best_effort_executor()
    shutdown_best_effort_executor()  # safe twice
    done = threading.Event()

    assert submit_best_effort(done.set) is True
    assert done.wait(WAIT)
