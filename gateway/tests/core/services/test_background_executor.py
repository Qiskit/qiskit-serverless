"""Tests for the background executor. Real threads, synchronised with events and timeouts."""

import logging
import threading
import time
from concurrent.futures import CancelledError, wait
from enum import Enum

import pytest
from prometheus_client import REGISTRY

from core.services import background_executor
from core.services.background_executor import (
    BackgroundExecutorNotInitializedError,
    BackgroundPool,
    get_background_executor,
)

executor = get_background_executor()
RUNTIME = BackgroundPool.RUNTIME_API

WAIT = 5


def _limit(per_pool: int) -> int:
    """A ``max_pending`` that gives every pool ``per_pool`` slots, however many pools the enum has."""
    return per_pool * len(BackgroundPool)


@pytest.fixture(name="clean_executor", autouse=True)
def clean_executor_fixture():
    executor.shutdown()
    yield
    executor.shutdown()


@pytest.fixture(name="release")
def release_fixture():
    """Tasks wait for this event. It is set at the end of the test even if an assertion failed, so none is left
    blocking the shutdown of the fixture above."""
    event = threading.Event()
    yield event
    event.set()


@pytest.fixture(name="small_pool")
def small_pool_fixture():
    executor.init(max_workers=2, max_pending=_limit(2))


@pytest.fixture(name="two_pools")
def two_pools_fixture(monkeypatch):
    """The real enum has a single pool for now, so stand in a second one."""

    class Pools(Enum):
        BIG = "big"
        SMALL = "small"

    monkeypatch.setattr(background_executor, "BackgroundPool", Pools)
    return Pools


def _submit_until_accepted(fn, pool=RUNTIME):
    """The wrapper frees its slot just after the task ends, so a submit right after may still see a full pool."""
    deadline = time.monotonic() + WAIT
    while time.monotonic() < deadline:
        if executor.submit(pool, fn):
            return True
        time.sleep(0.05)
    return False


def _sample(name, labels=None):
    return REGISTRY.get_sample_value(name, labels or {})


def test_submit_before_init_fails_loudly():
    with pytest.raises(BackgroundExecutorNotInitializedError):
        executor.submit(RUNTIME, lambda: None)


def test_a_second_init_is_an_error_until_shutdown():
    executor.init(max_workers=1, max_pending=_limit(1))

    with pytest.raises(RuntimeError):
        executor.init(max_workers=1, max_pending=_limit(1))

    executor.shutdown()
    executor.init(max_workers=1, max_pending=_limit(1))


def test_init_takes_its_defaults_from_settings(settings):
    settings.BACKGROUND_EXECUTOR_MAX_WORKERS = 3
    settings.BACKGROUND_EXECUTOR_MAX_PENDING = 7

    executor.init()

    assert executor.max_workers == 3
    assert executor.max_pending == 7
    assert _sample("background_executor_max_pending", {"pool": RUNTIME.value}) == 7 // len(BackgroundPool)


def test_the_task_runs_on_another_thread(small_pool):  # pylint: disable=unused-argument
    seen = []

    executor.submit(RUNTIME, lambda: seen.append(threading.current_thread())).result(WAIT)

    assert seen[0] is not threading.current_thread()


def test_a_full_pool_drops_the_next_task(small_pool, release):  # pylint: disable=unused-argument
    started = threading.Barrier(3)
    ran = []

    def blocker():
        started.wait(WAIT)
        release.wait(WAIT)

    assert executor.submit(RUNTIME, blocker) is not None
    assert executor.submit(RUNTIME, blocker) is not None
    started.wait(WAIT)

    assert executor.submit(RUNTIME, lambda: ran.append(1)) is None

    release.set()
    executor.shutdown()
    assert not ran


def test_every_pool_gets_an_even_share_of_the_limit(two_pools, release):
    executor.init(max_workers=1, max_pending=8)

    big = [executor.submit(two_pools.BIG, release.wait, WAIT) is not None for _ in range(5)]
    assert big == [True] * 4 + [False]  # BIG may not take the share of SMALL

    small = [executor.submit(two_pools.SMALL, release.wait, WAIT) is not None for _ in range(5)]
    assert small == [True] * 4 + [False]


def test_a_dropped_task_is_counted_under_its_own_pool(two_pools, release):
    executor.init(max_workers=1, max_pending=2)  # one slot each
    small_before = _sample("background_executor_dropped_total", {"pool": "small", "reason": "full"}) or 0
    big_before = _sample("background_executor_dropped_total", {"pool": "big", "reason": "full"}) or 0
    executor.submit(two_pools.SMALL, release.wait, WAIT)

    assert executor.submit(two_pools.SMALL, release.wait, WAIT) is None

    assert _sample("background_executor_dropped_total", {"pool": "small", "reason": "full"}) == small_before + 1
    assert (_sample("background_executor_dropped_total", {"pool": "big", "reason": "full"}) or 0) == big_before


def test_a_free_thread_goes_to_the_pool_with_fewer_tasks_running(two_pools):
    """SMALL was served first and still holds a thread; BIG holds none. The free thread must go to BIG, which a rule
    that only looked at who waited longer would not do."""
    executor.init(max_workers=2, max_pending=20)
    order = []
    small_started, big_started = threading.Event(), threading.Event()
    free_small, free_big = threading.Event(), threading.Event()

    def holder(started, free):
        started.set()
        free.wait(WAIT)

    try:
        executor.submit(two_pools.SMALL, holder, small_started, free_small)
        assert small_started.wait(WAIT)
        executor.submit(two_pools.BIG, holder, big_started, free_big)
        assert big_started.wait(WAIT)
        executor.submit(two_pools.SMALL, order.append, "small waiting")
        executor.submit(two_pools.BIG, order.append, "big waiting")

        free_big.set()  # one thread becomes free: SMALL runs 1 task, BIG runs 0
        deadline = time.monotonic() + WAIT
        while not order and time.monotonic() < deadline:
            time.sleep(0.02)
    finally:
        free_small.set()
        free_big.set()

    assert order[0] == "big waiting"


def test_a_failing_task_does_not_propagate_and_frees_its_slot(small_pool, caplog):  # pylint: disable=unused-argument
    def failing():
        raise RuntimeError("boom")

    with caplog.at_level(logging.WARNING, logger="core.BackgroundExecutor"):
        for _ in range(4):  # more than the slots: they must be given back
            future = executor.submit(RUNTIME, failing)
            assert future is not None
            with pytest.raises(RuntimeError):
                future.result(WAIT)

    assert "failing" in caplog.text and "boom" in caplog.text


def test_shutdown_twice_or_unused_is_safe_and_init_works_again():
    executor.shutdown()
    executor.init(max_workers=1, max_pending=_limit(1))
    executor.shutdown()
    executor.shutdown()
    executor.init(max_workers=1, max_pending=_limit(1))
    done = threading.Event()

    assert executor.submit(RUNTIME, done.set) is not None
    assert done.wait(WAIT)


def test_a_pool_created_in_another_process_is_refused(small_pool, monkeypatch):  # pylint: disable=unused-argument
    monkeypatch.setattr(background_executor.os, "getpid", lambda: -1)

    with pytest.raises(BackgroundExecutorNotInitializedError):
        executor.submit(RUNTIME, lambda: None)


def test_there_is_a_single_executor_per_process():
    assert get_background_executor() is get_background_executor()


def test_after_a_fork_the_locks_are_new_and_free():
    old_locks = (executor._lock, executor._lifecycle)  # pylint: disable=protected-access
    executor._lock.acquire()  # pylint: disable=protected-access,consider-using-with

    background_executor._reset_after_fork()  # pylint: disable=protected-access

    assert (executor._lock, executor._lifecycle) != old_locks  # pylint: disable=protected-access
    assert executor._lock.acquire(blocking=False)  # pylint: disable=protected-access
    executor._lock.release()  # pylint: disable=protected-access


def test_metrics_report_the_limits_the_outcomes_and_the_drops(small_pool, release):  # pylint: disable=unused-argument
    labels = {"pool": RUNTIME.value}
    done_before = _sample("background_executor_tasks_total", {**labels, "outcome": "completed"}) or 0
    failed_before = _sample("background_executor_tasks_total", {**labels, "outcome": "failed"}) or 0
    dropped_before = _sample("background_executor_dropped_total", {**labels, "reason": "full"}) or 0

    def boom():
        raise ValueError("x")

    assert _sample("background_executor_workers") == 2
    assert _sample("background_executor_max_pending", labels) == 2
    assert executor.submit(RUNTIME, release.wait, WAIT) is not None
    assert executor.submit(RUNTIME, release.wait, WAIT) is not None
    assert _sample("background_executor_pending", labels) == 2
    assert executor.submit(RUNTIME, boom) is None
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
        executor.init(**limits)

    with pytest.raises(BackgroundExecutorNotInitializedError):
        executor.submit(RUNTIME, lambda: None)


def test_a_thread_that_cannot_start_leaves_the_pool_uninitialized(monkeypatch):
    real_start = threading.Thread.start
    started = []

    def flaky_start(thread):
        started.append(thread)
        if len(started) == 2:
            raise RuntimeError("can't start new thread")
        real_start(thread)

    monkeypatch.setattr(threading.Thread, "start", flaky_start)
    with pytest.raises(RuntimeError):
        executor.init(max_workers=3, max_pending=_limit(1))
    monkeypatch.undo()

    with pytest.raises(BackgroundExecutorNotInitializedError):
        executor.submit(RUNTIME, lambda: None)
    started[0].join(WAIT)
    assert not started[0].is_alive()  # the thread that did start was stopped


def test_the_slot_is_released_even_if_closing_connections_fails(
    small_pool, monkeypatch
):  # pylint: disable=unused-argument
    def broken_close_all():
        raise RuntimeError("bad connection")

    monkeypatch.setattr(background_executor.connections, "close_all", broken_close_all)

    for _ in range(4):
        assert _submit_until_accepted(lambda: None) is True


def test_shutdown_counts_the_queued_tasks_it_cancels(release):
    executor.init(max_workers=1, max_pending=_limit(3))
    labels = {"pool": RUNTIME.value}
    started = threading.Event()
    assert executor.submit(RUNTIME, lambda: (started.set(), release.wait(WAIT))) is not None
    assert started.wait(WAIT)
    assert executor.submit(RUNTIME, lambda: None) is not None
    assert executor.submit(RUNTIME, lambda: None) is not None
    skipped_before = _sample("background_executor_tasks_total", {**labels, "outcome": "skipped"}) or 0

    threading.Timer(0.3, release.set).start()  # shutdown cancels the queue first, then waits for the running task
    executor.shutdown()

    assert _sample("background_executor_tasks_total", {**labels, "outcome": "skipped"}) == skipped_before + 2
    assert _sample("background_executor_pending", labels) == 0


def test_submit_returns_a_future_with_the_result_or_the_exception(small_pool):  # pylint: disable=unused-argument
    def boom():
        raise ValueError("x")

    assert executor.submit(RUNTIME, lambda: 42).result(WAIT) == 42
    with pytest.raises(ValueError):
        executor.submit(RUNTIME, boom).result(WAIT)


def test_a_batch_can_be_waited_for_in_one_go():
    executor.init(max_workers=2, max_pending=_limit(10))
    done_by = []

    futures = [executor.submit(RUNTIME, done_by.append, n) for n in range(4)]
    done, not_done = wait(futures, timeout=WAIT)

    assert len(done) == 4 and not not_done
    assert sorted(done_by) == [0, 1, 2, 3]


def test_the_slot_is_already_free_when_the_future_is_resolved():
    executor.init(max_workers=1, max_pending=_limit(1))
    seen = []
    resolved = threading.Event()
    callback_added = threading.Event()

    def task():
        callback_added.wait(WAIT)

    future = executor.submit(RUNTIME, task)
    future.add_done_callback(lambda _future: (seen.append(executor.status(RUNTIME)), resolved.set()))
    callback_added.set()

    assert resolved.wait(WAIT)
    assert (seen[0].running, seen[0].free_slots) == (0, 1)  # read from inside the callback of the very future


def test_status_reports_the_queue_the_running_tasks_the_free_slots_and_the_idle_workers(release):
    executor.init(max_workers=2, max_pending=_limit(10))
    started = threading.Barrier(3)

    def blocker():
        started.wait(WAIT)
        release.wait(WAIT)

    assert executor.status(RUNTIME) == (0, 0, 10, 2)
    executor.submit(RUNTIME, blocker)
    executor.submit(RUNTIME, blocker)
    started.wait(WAIT)
    executor.submit(RUNTIME, lambda: None)

    assert executor.status(RUNTIME) == (1, 2, 7, 0)


def test_status_before_init_fails_loudly():
    with pytest.raises(BackgroundExecutorNotInitializedError):
        executor.status(RUNTIME)


def test_shutdown_cancels_the_queued_futures_and_releases_whoever_waits_for_them(release):
    executor.init(max_workers=1, max_pending=_limit(5))
    started = threading.Event()
    running = executor.submit(RUNTIME, lambda: (started.set(), release.wait(WAIT)))
    assert started.wait(WAIT)
    queued = executor.submit(RUNTIME, lambda: None)

    threading.Timer(0.3, release.set).start()
    executor.shutdown()
    _, not_done = wait([running, queued], timeout=WAIT)

    assert not not_done
    assert queued.cancelled()
    with pytest.raises(CancelledError):
        queued.result()


def test_a_future_cancelled_while_queued_gives_its_slot_back_at_once(release):
    executor.init(max_workers=1, max_pending=_limit(2))
    started = threading.Event()
    executor.submit(RUNTIME, lambda: (started.set(), release.wait(WAIT)))
    assert started.wait(WAIT)
    queued = executor.submit(RUNTIME, lambda: None)
    assert executor.status(RUNTIME).free_slots == 0  # one running, one queued

    assert queued.cancel() is True

    assert executor.status(RUNTIME).free_slots == 1  # the thread is still busy: nobody had to reach the task
    assert executor.status(RUNTIME).queued == 0
    done, _ = wait([queued], timeout=WAIT)
    assert done  # and whoever waits for it is released too


def test_shutdown_from_inside_a_task_does_not_fail(small_pool):  # pylint: disable=unused-argument
    future = executor.submit(RUNTIME, executor.shutdown)

    assert future.result(WAIT) is None
    with pytest.raises(BackgroundExecutorNotInitializedError):
        executor.submit(RUNTIME, lambda: None)


def test_init_waits_for_a_shutdown_in_progress_so_the_gauges_do_not_go_negative(release):
    executor.init(max_workers=1, max_pending=_limit(1))
    started = threading.Event()
    executor.submit(RUNTIME, lambda: (started.set(), release.wait(WAIT)))
    assert started.wait(WAIT)
    labels = {"pool": RUNTIME.value}

    stopper = threading.Thread(target=executor.shutdown)
    stopper.start()
    time.sleep(0.2)  # the shutdown is now waiting for the running task
    starter = threading.Thread(target=lambda: executor.init(max_workers=1, max_pending=_limit(1)))
    starter.start()
    time.sleep(0.2)
    release.set()
    stopper.join(WAIT)
    starter.join(WAIT)

    assert _sample("background_executor_pending", labels) == 0
    assert _sample("background_executor_running", labels) == 0
