"""One shared thread pool per process for background work: tasks whose result nobody waits for.

There is a single ``BackgroundExecutor`` per process; get it with ``get_background_executor()``. Call ``init()`` on it
once at startup, in every process that uses it (the scheduler in ``scheduler/main.py``). ``submit`` fails loudly with
``BackgroundExecutorNotInitializedError`` if ``init`` was not called, or if the pool belongs to another process: a
forked child inherits the object but not the threads, so it must call ``init`` again.

Every caller in a process shares the same threads, so the total number of background threads stays bounded by
``settings.BACKGROUND_EXECUTOR_MAX_WORKERS``. Each caller submits under a ``BackgroundPool`` name, and every pool gets
the same share: it may have at most ``settings.BACKGROUND_EXECUTOR_MAX_PENDING`` divided by the number of pools tasks
submitted and unfinished (queued or running). The next one is dropped and ``submit`` returns None. Dropping is by
design: this is not a queue. Nothing needs configuring when a pool is added: the share is recomputed from the enum.

The threads are shared, not split. A thread that becomes free serves the pool with the fewest tasks running, among the
pools with tasks waiting (the one served least recently breaks a tie). So a slow service that holds every thread
cannot make the others wait longer than one of its tasks, and the threads move towards an even split as they free up.
A pool with nothing waiting does not hold any threads back: the others can use all of them. Tasks are not preempted,
so a pool that finds every thread busy waits for the first one to finish.

``submit`` returns a ``concurrent.futures.Future``, or ``None`` when the task was dropped. A caller that does not care
about the result ignores it (fire and forget). One that wants to wait for a group of tasks uses
``concurrent.futures.wait(futures)`` or ``future.done()``. ``status(pool)`` says how loaded a pool is, to decide
whether to submit more now or on the next tick::

    executor = get_background_executor()
    pool = BackgroundPool.RUNTIME_API
    status = executor.status(pool)
    if status.queued == 0 and status.free_slots >= 4 and status.idle_workers >= 4:  # all four would start at once
        sent = [executor.submit(pool, send, job_id) for job_id in next_four]
        self.in_flight = [future for future in sent if future is not None]  # None is a task that was dropped
    ...
    done, not_done = concurrent.futures.wait(self.in_flight, timeout=0)  # timeout=0 does not block

``queued == 0`` alone is not enough to know that a task will start soon: the threads are shared, so another pool can
be holding all of them. That is what ``idle_workers`` tells. With a single thread submitting (the scheduler) the status
can only get freer after it is read, so it is reliable; with several, check what ``submit`` returns.
The future of a task that ran is resolved after its slot is free, so ``status`` right after a ``wait`` already counts
it. A task cancelled with ``future.cancel()`` while it is still queued gives its slot back at once.

Tasks must be short and must not depend on the caller's request or transaction. A task that raises is logged, and the
exception is kept in its future. Worker threads open their own database connections, which are closed when each task
ends.

``shutdown()`` lets the tasks that are running finish (each bounded by its own request timeouts) and cancels the queued
ones, so whoever waits for them is released. The owner of the process should call it; the scheduler does, in the
``finally`` of its loop. The threads are daemons, so a process that never calls it is not kept alive at exit: tasks
still running are abandoned and queued ones are lost.

Once the pool has threads, ``os.fork()`` in ``api/domain/isolated.py`` runs in a multi-threaded process and Python
3.12 may emit a DeprecationWarning. It is safe there because the child only validates and leaves through
``os._exit``, so do not "fix" the warning by touching connections in the child.

Adopting it in the gateway needs ``init()`` in every gunicorn worker after the fork (``main/wsgi.py`` is imported
there) and ``shutdown()`` from a ``worker_exit`` hook, for a clean exit. Each process has its own pool, so the limits
multiply by the number of workers.

Metrics are published on the default prometheus_client registry, which the gateway (django_prometheus) and the
scheduler already expose. ``background_executor_workers`` is the configured number of threads. Per pool:
``background_executor_max_pending`` (its limit), ``background_executor_pending`` (accepted and unfinished, running
included), ``background_executor_running``, ``background_executor_tasks_total{outcome}`` (completed, failed or skipped
at shutdown, or cancelled by the caller while queued), ``background_executor_dropped_total{reason}`` (full or
shut_down) and ``background_executor_task_duration_seconds``. Compare ``pending`` with ``max_pending`` and watch
``dropped_total`` to size the pool. Every process reports its own numbers: the gateway has several, so aggregate across
them in the query.

The Kafka sender could adopt this pool later.
"""

import logging
import os
import threading
import time
from collections import deque
from concurrent.futures import Future
from enum import Enum
from typing import Callable, NamedTuple

from django.conf import settings
from django.db import connections
from prometheus_client import Counter, Gauge, Histogram

logger = logging.getLogger("core.BackgroundExecutor")


class BackgroundExecutorNotInitializedError(RuntimeError):
    """``BackgroundExecutor.submit`` was called before ``init``, or in a process other than the one that called it."""


class PoolStatus(NamedTuple):
    """How loaded a pool is, read in one go. ``queued`` tasks wait for a thread, ``running`` ones have it,
    ``free_slots`` is how many more tasks ``submit`` would accept for this pool right now, and ``idle_workers`` how many
    threads of the process have nothing to do."""

    queued: int
    running: int
    free_slots: int
    idle_workers: int


class BackgroundPool(Enum):
    """Who is submitting. Add a member for each new caller: the pools split the limit evenly."""

    RUNTIME_API = "runtime_api"  # calls to the Runtime API


_WORKERS = Gauge("background_executor_workers", "Configured number of worker threads of this process.")
_MAX_PENDING = Gauge(
    "background_executor_max_pending", "Limit of accepted and unfinished tasks of the pool.", labelnames=("pool",)
)
_PENDING = Gauge(
    "background_executor_pending",
    "Tasks accepted and not finished yet, running ones included.",
    labelnames=("pool",),
)
_RUNNING = Gauge("background_executor_running", "Tasks running on a worker thread right now.", labelnames=("pool",))
_TASKS = Counter("background_executor_tasks_total", "Finished tasks by outcome.", labelnames=("pool", "outcome"))
_DROPPED = Counter("background_executor_dropped_total", "Tasks that were not accepted.", labelnames=("pool", "reason"))
_DURATION = Histogram(
    "background_executor_task_duration_seconds", "Run time of one background task.", labelnames=("pool",)
)


class _Cycle:  # pylint: disable=too-many-instance-attributes
    """The state of one ``init()`` to ``shutdown()`` cycle. Its threads keep a reference to it, so a late task of an
    old cycle never touches the counters of a new one. Everything here is guarded by ``cond``."""

    def __init__(self, max_workers: int, pool_limit: int) -> None:
        self.max_workers = max_workers
        self.pool_limit = pool_limit
        self.cond = threading.Condition()
        self.queues: dict[BackgroundPool, deque] = {pool: deque() for pool in BackgroundPool}
        self.running = {pool: 0 for pool in BackgroundPool}
        self.served = {pool: 0 for pool in BackgroundPool}  # when each pool last started a task; lower waited longer
        self.clock = 0
        self.stopping = False
        self.threads = [
            threading.Thread(target=self._work, name=f"background-{i}", daemon=True) for i in range(max_workers)
        ]

    def forget_if_cancelled(self, pool: BackgroundPool, item: tuple) -> None:
        """Done callback of a queued task: if the caller cancelled it, take it out of the queue now, so its slot is free
        and whoever waits for it is released. A thread that already took it accounts for it by itself."""
        future = item[0]
        if not future.cancelled():
            return
        with self.cond:
            try:
                self.queues[pool].remove(item)
            except ValueError:
                return
            _TASKS.labels(pool.value, "skipped").inc()
            _PENDING.labels(pool.value).dec()
        future.set_running_or_notify_cancel()  # wakes whoever waits for it

    def pending(self, pool: BackgroundPool) -> int:
        """Tasks of ``pool`` accepted and not finished: waiting plus running."""
        return len(self.queues[pool]) + self.running[pool]

    def _next_pool(self) -> BackgroundPool | None:
        waiting = [pool for pool in BackgroundPool if self.queues[pool]]
        if not waiting:
            return None
        return min(waiting, key=lambda pool: (self.running[pool], self.served[pool]))

    def _work(self) -> None:
        while True:
            with self.cond:
                pool = self._next_pool()
                while pool is None and not self.stopping:
                    self.cond.wait()
                    pool = self._next_pool()
                if self.stopping:
                    return
                future, fn, args, kwargs = self.queues[pool].popleft()
                self.running[pool] += 1
                self.clock += 1
                self.served[pool] = self.clock
            try:
                self._execute(pool, future, fn, args, kwargs)
            except Exception:  # pylint: disable=broad-exception-caught
                logger.exception("background worker failed while finishing a task")  # keep the thread alive

    def _execute(self, pool: BackgroundPool, future: Future, fn: Callable, args: tuple, kwargs: dict) -> None:
        if future.cancelled():  # cancelled just after a thread took it: free the slot, then wake the waiters
            try:
                self._finish(pool, "skipped")
            finally:
                future.set_running_or_notify_cancel()
            return
        if not future.set_running_or_notify_cancel():  # cancelled in the instant between the two calls
            self._finish(pool, "skipped")
            return
        result, error, outcome = None, None, "completed"
        _RUNNING.labels(pool.value).inc()
        started = time.monotonic()
        try:
            result = fn(*args, **kwargs)
        except BaseException as exc:  # pylint: disable=broad-exception-caught
            error, outcome = exc, "failed"
            logger.warning("background task %s failed: %r", getattr(fn, "__qualname__", fn), exc, exc_info=True)
        finally:
            _RUNNING.labels(pool.value).dec()
            _DURATION.labels(pool.value).observe(time.monotonic() - started)
        try:
            self._finish(pool, outcome)
        finally:
            # last, so whoever waits for the future finds the slot already free
            if error is not None:
                future.set_exception(error)
            else:
                future.set_result(result)

    def _finish(self, pool: BackgroundPool, outcome: str) -> None:
        try:
            _TASKS.labels(pool.value, outcome).inc()
            _PENDING.labels(pool.value).dec()
            connections.close_all()
        finally:
            with self.cond:
                self.running[pool] -= 1  # a failing close must not leak the slot


class BackgroundExecutor:
    """The pool of this process. Do not build it: use ``get_background_executor()``."""

    def __init__(self) -> None:
        self._lifecycle = threading.Lock()  # one init() or shutdown() at a time, so the gauges of two cycles never mix
        self._lock = threading.Lock()  # guards the next three
        self._cycle: _Cycle | None = None
        self._pid: int | None = None
        self.max_workers = 0
        self.max_pending = 0

    def init(self, max_workers: int | None = None, max_pending: int | None = None) -> None:
        """Create the pool of this process. The limits default to ``settings.BACKGROUND_EXECUTOR_MAX_WORKERS`` and
        ``settings.BACKGROUND_EXECUTOR_MAX_PENDING``. Raises RuntimeError if this process already has a pool, unless
        ``shutdown`` was called in between."""
        with self._lifecycle, self._lock:
            if self._cycle is not None and self._pid == os.getpid():
                raise RuntimeError("BackgroundExecutor is already initialized in this process")
            workers = settings.BACKGROUND_EXECUTOR_MAX_WORKERS if max_workers is None else max_workers
            pending = settings.BACKGROUND_EXECUTOR_MAX_PENDING if max_pending is None else max_pending
            if workers < 1 or pending < 0:  # validate before anything is stored or started
                raise ValueError("max_workers must be at least 1 and max_pending must not be negative")
            cycle = _Cycle(workers, pending // len(BackgroundPool))
            try:
                for thread in cycle.threads:
                    thread.start()
            except RuntimeError:  # could not start a thread: stop the ones that did start
                with cycle.cond:
                    cycle.stopping = True
                    cycle.cond.notify_all()
                raise
            self.max_workers, self.max_pending = workers, pending
            self._cycle, self._pid = cycle, os.getpid()
            _WORKERS.set(workers)
            for pool in BackgroundPool:
                _MAX_PENDING.labels(pool.value).set(cycle.pool_limit)
                _PENDING.labels(pool.value).set(0)
                _RUNNING.labels(pool.value).set(0)

    def _current_cycle(self) -> _Cycle:
        with self._lock:
            cycle, owner = self._cycle, self._pid
        if cycle is None or owner != os.getpid():
            raise BackgroundExecutorNotInitializedError("BackgroundExecutor.init() was not called in this process")
        return cycle

    def submit(self, pool: BackgroundPool, fn: Callable, *args, **kwargs) -> Future | None:
        """Run ``fn(*args, **kwargs)`` on a thread and return at once with its ``Future``. Returns None, without
        running it, when the ``pool`` already has its share of tasks pending. Raises
        BackgroundExecutorNotInitializedError if ``init`` was not called in this process."""
        cycle = self._current_cycle()
        future: Future = Future()
        with cycle.cond:
            reason = "shut_down" if cycle.stopping else "full" if cycle.pending(pool) >= cycle.pool_limit else None
            if reason is None:
                item = (future, fn, args, kwargs)
                cycle.queues[pool].append(item)
                _PENDING.labels(pool.value).inc()
                future.add_done_callback(lambda _future: cycle.forget_if_cancelled(pool, item))
                cycle.cond.notify()
                return future
        _DROPPED.labels(pool.value, reason).inc()
        logger.warning(
            "background pool %s is %s, task dropped", pool.value, "shut down" if reason == "shut_down" else "full"
        )
        return None

    def status(self, pool: BackgroundPool) -> PoolStatus:
        """How loaded ``pool`` is right now. Raises BackgroundExecutorNotInitializedError if ``init`` was not called in
        this process."""
        cycle = self._current_cycle()
        with cycle.cond:
            running_total = sum(cycle.running.values())
            return PoolStatus(
                queued=len(cycle.queues[pool]),
                running=cycle.running[pool],
                free_slots=max(0, cycle.pool_limit - cycle.pending(pool)),
                idle_workers=max(0, cycle.max_workers - running_total),
            )

    def shutdown(self) -> None:
        """Stop the pool of this process: running tasks finish (each ends within its own timeouts), queued ones are
        cancelled. Safe to call twice or when never initialized; ``init`` can be called again afterwards, and waits
        until a shutdown in progress has finished."""
        with self._lifecycle:
            with self._lock:
                cycle, owner = self._cycle, self._pid
                self._cycle, self._pid = None, None
            if cycle is None or owner != os.getpid():
                return
            with cycle.cond:
                cycle.stopping = True
                for queue in cycle.queues.values():
                    for future, *_ in list(queue):
                        future.cancel()  # its done callback takes it out of the queue and counts it as skipped
                cycle.cond.notify_all()
            for thread in cycle.threads:
                if thread is not threading.current_thread():  # a task may call shutdown itself
                    thread.join()


_instance = BackgroundExecutor()


def get_background_executor() -> BackgroundExecutor:
    """The one ``BackgroundExecutor`` of this process. It still needs ``init()`` before ``submit``."""
    return _instance


def _reset_after_fork() -> None:
    # A thread of the parent may have held the lock at fork time; the child's copy would stay locked forever.
    _instance._lock = threading.Lock()  # pylint: disable=protected-access
    _instance._lifecycle = threading.Lock()  # pylint: disable=protected-access


os.register_at_fork(after_in_child=_reset_after_fork)
