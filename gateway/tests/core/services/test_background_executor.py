"""Tests for the background executor. Real threads, synchronised with events and timeouts."""

import logging
import threading
import time

import pytest
from prometheus_client import REGISTRY

from core.services import background_executor
from core.services.background_executor import BackgroundExecutorNotInitializedError, get_background_executor

BackgroundExecutor = get_background_executor()
_State = BackgroundExecutor

WAIT = 5


@pytest.fixture(name="clean_executor", autouse=True)
def clean_executor_fixture():
    BackgroundExecutor.shutdown()
    yield
    _State.closing = False
    BackgroundExecutor.shutdown()


@pytest.fixture(name="small_pool")
def small_pool_fixture():
    BackgroundExecutor.init(max_workers=2, max_pending=2)


def _submit_until_accepted(fn):
    """The wrapper frees its slot just after the task ends, so a submit right after may still see a full pool."""
    deadline = time.monotonic() + WAIT
    while time.monotonic() < deadline:
        if BackgroundExecutor.submit(fn):
            return True
        time.sleep(0.05)
    return False


def test_submit_before_init_fails_loudly():
    with pytest.raises(BackgroundExecutorNotInitializedError):
        BackgroundExecutor.submit(lambda: None)


def test_a_second_init_is_an_error_until_shutdown():
    BackgroundExecutor.init(max_workers=1, max_pending=1)

    with pytest.raises(RuntimeError):
        BackgroundExecutor.init(max_workers=1, max_pending=1)

    BackgroundExecutor.shutdown()
    BackgroundExecutor.init(max_workers=1, max_pending=1)


def test_init_takes_its_defaults_from_settings(settings):
    settings.BACKGROUND_EXECUTOR_MAX_WORKERS = 3
    settings.BACKGROUND_EXECUTOR_MAX_PENDING = 7

    BackgroundExecutor.init()

    assert _State._executor._max_workers == 3  # pylint: disable=protected-access
    assert _State._slots._initial_value == 7  # pylint: disable=protected-access


def test_the_task_runs_on_another_thread(small_pool):  # pylint: disable=unused-argument
    done = threading.Event()
    seen = []

    def task():
        seen.append(threading.current_thread())
        done.set()

    assert BackgroundExecutor.submit(task) is True
    assert done.wait(WAIT)
    assert seen[0] is not threading.current_thread()


def test_a_full_pool_drops_the_next_task(small_pool):  # pylint: disable=unused-argument
    release = threading.Event()
    started = threading.Barrier(3)
    ran = []

    def blocker():
        started.wait(WAIT)
        release.wait(WAIT)

    assert BackgroundExecutor.submit(blocker) is True
    assert BackgroundExecutor.submit(blocker) is True
    started.wait(WAIT)

    assert BackgroundExecutor.submit(lambda: ran.append(1)) is False

    release.set()
    BackgroundExecutor.shutdown()
    assert not ran


def test_a_failing_task_does_not_propagate_and_frees_its_slot(small_pool, caplog):  # pylint: disable=unused-argument
    finished = threading.Barrier(3)

    def failing():
        try:
            raise RuntimeError("boom")
        finally:
            finished.wait(WAIT)

    with caplog.at_level(logging.WARNING, logger="core.BackgroundExecutor"):
        assert BackgroundExecutor.submit(failing) is True
        assert BackgroundExecutor.submit(failing) is True
        finished.wait(WAIT)

        assert _submit_until_accepted(lambda: None) is True

    assert "failing" in caplog.text and "boom" in caplog.text


def test_queued_tasks_are_skipped_once_the_interpreter_is_closing(small_pool):  # pylint: disable=unused-argument
    ran = []
    _State.closing = True

    assert BackgroundExecutor.submit(lambda: ran.append(1)) is True
    assert BackgroundExecutor.submit(lambda: ran.append(2)) is True  # max_pending is 2: the pool is now full

    assert _submit_until_accepted(lambda: None) is True  # only possible if the skipped tasks released their slots
    assert not ran


def test_shutdown_twice_or_unused_is_safe_and_init_works_again():
    BackgroundExecutor.shutdown()
    BackgroundExecutor.init(max_workers=1, max_pending=1)
    BackgroundExecutor.shutdown()
    BackgroundExecutor.shutdown()
    BackgroundExecutor.init(max_workers=1, max_pending=1)
    done = threading.Event()

    assert BackgroundExecutor.submit(done.set) is True
    assert done.wait(WAIT)


def test_a_pool_created_in_another_process_is_refused(small_pool, monkeypatch):  # pylint: disable=unused-argument
    monkeypatch.setattr(background_executor.os, "getpid", lambda: -1)

    with pytest.raises(BackgroundExecutorNotInitializedError):
        BackgroundExecutor.submit(lambda: None)


def test_there_is_a_single_executor_per_process():
    assert get_background_executor() is get_background_executor()


def _sample(name, labels=None):
    return REGISTRY.get_sample_value(name, labels or {})


def test_metrics_report_the_limits_the_outcomes_and_the_drops(small_pool):
    done_before = _sample("background_executor_tasks_total", {"outcome": "completed"}) or 0
    failed_before = _sample("background_executor_tasks_total", {"outcome": "failed"}) or 0
    dropped_before = _sample("background_executor_dropped_total", {"reason": "full"}) or 0
    release = threading.Event()

    def boom():
        raise ValueError("x")

    assert _sample("background_executor_workers") == 2
    assert _sample("background_executor_max_pending") == 2
    assert BackgroundExecutor.submit(release.wait) is True
    assert BackgroundExecutor.submit(release.wait) is True
    assert _sample("background_executor_pending") == 2
    assert BackgroundExecutor.submit(boom) is False
    release.set()
    assert _submit_until_accepted(boom)
    assert _submit_until_accepted(lambda: None)
    deadline = time.monotonic() + WAIT
    while _sample("background_executor_pending") and time.monotonic() < deadline:
        time.sleep(0.05)

    assert _sample("background_executor_dropped_total", {"reason": "full"}) >= dropped_before + 1
    assert _sample("background_executor_tasks_total", {"outcome": "completed"}) >= done_before + 2
    assert _sample("background_executor_tasks_total", {"outcome": "failed"}) == failed_before + 1
    assert _sample("background_executor_pending") == 0
