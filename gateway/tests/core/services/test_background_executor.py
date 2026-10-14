"""Tests for the background executor. Real threads, synchronised with events and timeouts."""

import logging
from enum import Enum
import threading
import time

import pytest
from prometheus_client import REGISTRY

from core.services import background_executor
from core.services.background_executor import (
    BackgroundExecutorNotInitializedError,
    BackgroundPool,
    get_background_executor,
)

BackgroundExecutor = get_background_executor()
RUNTIME = BackgroundPool.RUNTIME_API

WAIT = 5


@pytest.fixture(name="clean_executor", autouse=True)
def clean_executor_fixture():
    BackgroundExecutor.shutdown()
    yield
    BackgroundExecutor.shutdown()


@pytest.fixture(name="small_pool")
def small_pool_fixture():
    BackgroundExecutor.init(max_workers=2, max_pending=2)


def _submit_until_accepted(fn, pool=RUNTIME):
    """The wrapper frees its slot just after the task ends, so a submit right after may still see a full pool."""
    deadline = time.monotonic() + WAIT
    while time.monotonic() < deadline:
        if BackgroundExecutor.submit(pool, fn):
            return True
        time.sleep(0.05)
    return False


def _sample(name, labels=None):
    return REGISTRY.get_sample_value(name, labels or {})


def test_submit_before_init_fails_loudly():
    with pytest.raises(BackgroundExecutorNotInitializedError):
        BackgroundExecutor.submit(RUNTIME, lambda: None)


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

    assert BackgroundExecutor.max_workers == 3
    assert BackgroundExecutor.max_pending == 7
    assert _sample("background_executor_max_pending", {"pool": RUNTIME.value}) == 7  # a single pool gets it all


def test_the_task_runs_on_another_thread(small_pool):  # pylint: disable=unused-argument
    done = threading.Event()
    seen = []

    def task():
        seen.append(threading.current_thread())
        done.set()

    assert BackgroundExecutor.submit(RUNTIME, task) is True
    assert done.wait(WAIT)
    assert seen[0] is not threading.current_thread()


def test_a_full_pool_drops_the_next_task(small_pool):  # pylint: disable=unused-argument
    release = threading.Event()
    started = threading.Barrier(3)
    ran = []

    def blocker():
        started.wait(WAIT)
        release.wait(WAIT)

    assert BackgroundExecutor.submit(RUNTIME, blocker) is True
    assert BackgroundExecutor.submit(RUNTIME, blocker) is True
    started.wait(WAIT)

    assert BackgroundExecutor.submit(RUNTIME, lambda: ran.append(1)) is False

    release.set()
    BackgroundExecutor.shutdown()
    assert not ran


@pytest.fixture(name="two_pools")
def two_pools_fixture(monkeypatch):
    """The real enum has a single pool for now, so stand in a second one."""

    class Pools(Enum):
        BIG = "big"
        SMALL = "small"

    monkeypatch.setattr(background_executor, "BackgroundPool", Pools)
    return Pools


def test_every_pool_gets_an_even_share_of_the_limit(two_pools):
    BackgroundExecutor.init(max_workers=1, max_pending=8)
    release = threading.Event()

    accepted = [BackgroundExecutor.submit(two_pools.BIG, release.wait) for _ in range(5)]
    assert accepted == [True] * 4 + [False]  # BIG may not take the share of SMALL

    assert [BackgroundExecutor.submit(two_pools.SMALL, release.wait) for _ in range(5)] == [True] * 4 + [False]

    release.set()


def test_a_free_thread_serves_the_pool_with_the_fewest_tasks_running(two_pools):
    BackgroundExecutor.init(max_workers=1, max_pending=20)
    order = []
    started = threading.Event()
    release = threading.Event()

    def blocker():
        started.set()
        release.wait(WAIT)

    assert BackgroundExecutor.submit(two_pools.BIG, blocker) is True
    assert started.wait(WAIT)
    for name in ("big 1", "big 2"):
        assert BackgroundExecutor.submit(two_pools.BIG, order.append, name) is True
    assert BackgroundExecutor.submit(two_pools.SMALL, order.append, "small 1") is True

    release.set()
    deadline = time.monotonic() + WAIT
    while len(order) < 3 and time.monotonic() < deadline:
        time.sleep(0.05)

    assert order[0] == "small 1"  # it arrived last, but BIG already had the thread


def test_a_failing_task_does_not_propagate_and_frees_its_slot(small_pool, caplog):  # pylint: disable=unused-argument
    finished = threading.Barrier(3)

    def failing():
        try:
            raise RuntimeError("boom")
        finally:
            finished.wait(WAIT)

    with caplog.at_level(logging.WARNING, logger="core.BackgroundExecutor"):
        assert BackgroundExecutor.submit(RUNTIME, failing) is True
        assert BackgroundExecutor.submit(RUNTIME, failing) is True
        finished.wait(WAIT)

        assert _submit_until_accepted(lambda: None) is True

    assert "failing" in caplog.text and "boom" in caplog.text


def test_shutdown_twice_or_unused_is_safe_and_init_works_again():
    BackgroundExecutor.shutdown()
    BackgroundExecutor.init(max_workers=1, max_pending=1)
    BackgroundExecutor.shutdown()
    BackgroundExecutor.shutdown()
    BackgroundExecutor.init(max_workers=1, max_pending=1)
    done = threading.Event()

    assert BackgroundExecutor.submit(RUNTIME, done.set) is True
    assert done.wait(WAIT)


def test_a_pool_created_in_another_process_is_refused(small_pool, monkeypatch):  # pylint: disable=unused-argument
    monkeypatch.setattr(background_executor.os, "getpid", lambda: -1)

    with pytest.raises(BackgroundExecutorNotInitializedError):
        BackgroundExecutor.submit(RUNTIME, lambda: None)


def test_there_is_a_single_executor_per_process():
    assert get_background_executor() is get_background_executor()


def test_metrics_report_the_limits_the_outcomes_and_the_drops(small_pool):  # pylint: disable=unused-argument
    labels = {"pool": RUNTIME.value}
    done_before = _sample("background_executor_tasks_total", {**labels, "outcome": "completed"}) or 0
    failed_before = _sample("background_executor_tasks_total", {**labels, "outcome": "failed"}) or 0
    dropped_before = _sample("background_executor_dropped_total", {**labels, "reason": "full"}) or 0
    release = threading.Event()

    def boom():
        raise ValueError("x")

    assert _sample("background_executor_workers") == 2
    assert _sample("background_executor_max_pending", labels) == 2
    assert BackgroundExecutor.submit(RUNTIME, release.wait) is True
    assert BackgroundExecutor.submit(RUNTIME, release.wait) is True
    assert _sample("background_executor_pending", labels) == 2
    assert BackgroundExecutor.submit(RUNTIME, boom) is False
    release.set()
    assert _submit_until_accepted(boom)
    assert _submit_until_accepted(lambda: None)
    deadline = time.monotonic() + WAIT
    while _sample("background_executor_pending", labels) and time.monotonic() < deadline:
        time.sleep(0.05)

    assert _sample("background_executor_dropped_total", {**labels, "reason": "full"}) >= dropped_before + 1
    assert _sample("background_executor_tasks_total", {**labels, "outcome": "completed"}) >= done_before + 2
    assert _sample("background_executor_tasks_total", {**labels, "outcome": "failed"}) == failed_before + 1
    assert _sample("background_executor_pending", labels) == 0


@pytest.mark.parametrize("limits", [{"max_workers": 1, "max_pending": -1}, {"max_workers": 0, "max_pending": 1}])
def test_an_invalid_limit_leaves_the_pool_uninitialized(limits):
    with pytest.raises(ValueError):
        BackgroundExecutor.init(**limits)

    with pytest.raises(BackgroundExecutorNotInitializedError):
        BackgroundExecutor.submit(RUNTIME, lambda: None)


def test_the_slot_is_released_even_if_closing_connections_fails(
    small_pool, monkeypatch
):  # pylint: disable=unused-argument
    def broken_close_all():
        raise RuntimeError("bad connection")

    monkeypatch.setattr(background_executor.connections, "close_all", broken_close_all)

    for _ in range(4):
        assert _submit_until_accepted(lambda: None) is True


def test_shutdown_counts_the_queued_tasks_it_cancels():
    BackgroundExecutor.init(max_workers=1, max_pending=3)
    labels = {"pool": RUNTIME.value}
    release = threading.Event()
    started = threading.Event()
    assert BackgroundExecutor.submit(RUNTIME, lambda: (started.set(), release.wait(WAIT))) is True
    assert started.wait(WAIT)
    assert BackgroundExecutor.submit(RUNTIME, lambda: None) is True
    assert BackgroundExecutor.submit(RUNTIME, lambda: None) is True
    skipped_before = _sample("background_executor_tasks_total", {**labels, "outcome": "skipped"}) or 0

    threading.Timer(0.3, release.set).start()  # shutdown cancels the queue first, then waits for the running task
    BackgroundExecutor.shutdown()

    assert _sample("background_executor_tasks_total", {**labels, "outcome": "skipped"}) == skipped_before + 2
    assert _sample("background_executor_pending", labels) == 0
