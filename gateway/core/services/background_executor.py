"""One shared thread pool per process for background work: tasks whose result nobody waits for.

There is a single ``BackgroundExecutor`` per process; get it with ``get_background_executor()``. Call ``init()`` on it
once at startup, in every process that uses it (the scheduler in ``scheduler/main.py``). ``submit`` fails loudly with
``BackgroundExecutorNotInitializedError`` if ``init`` was not called, or if the pool belongs to another process: a
forked child inherits the object but not the threads, so it must call ``init`` again.

Every caller in a process shares the same threads, so the total number of background threads stays bounded by
``settings.BACKGROUND_EXECUTOR_MAX_WORKERS`` ("worker" is the name the standard library gives to the threads of a
pool, as in ``ThreadPoolExecutor(max_workers=...)``; here they are always threads). Each caller submits under a
``BackgroundPool`` name, and every pool gets the same share: it may have at most
``settings.BACKGROUND_EXECUTOR_MAX_PENDING`` divided by the number of pools tasks submitted and unfinished (queued or
running). The next one is dropped and ``submit`` returns None, unless it replaces a waiting task (see ``replace_key``
below). Dropping is by design: this is not a queue. Nothing needs configuring when a pool is added: the share is
recomputed from the enum.

The threads are shared, not split. A thread that becomes free serves the pool with the fewest tasks running, among the
pools with tasks waiting (the one served least recently breaks a tie). So a slow service that holds every thread
cannot make the others wait longer than one of its tasks, and the threads move towards an even split as they free up.
A pool with nothing waiting does not hold any threads back: the others can use all of them. Tasks are not preempted,
so a pool that finds every thread busy waits for the first one to finish.

``submit`` returns a ``concurrent.futures.Future``, or ``None`` when the task was dropped. A caller that does not care
about the result ignores it (fire and forget). One that wants to wait for a group of tasks uses
``concurrent.futures.wait(futures)`` or ``future.done()``. ``status(pool)`` says how loaded a pool is, to decide
whether to submit more now or on the next tick (``free_slots`` counts new slots only: it knows nothing about
``replace_key``, see below)::

    executor = get_background_executor()
    pool = BackgroundPool.RUNTIME_API
    status = executor.status(pool)
    if status.queued == 0 and status.free_slots >= 4 and status.idle_workers >= 4:  # all four would start at once
        sent = [executor.submit(pool, send, job_id) for job_id in next_four]
        self.in_flight = [future for future in sent if future is not None]  # None is a task that was dropped
    ...
    done, not_done = concurrent.futures.wait(self.in_flight, timeout=0)  # timeout=0 does not block

``queued == 0`` alone is not enough to know that a task will start soon: the threads are shared, so another pool can
be holding all of them. That is what ``idle_workers`` (the idle threads) tells. With a single thread submitting (the
scheduler) the status can only get freer after it is read, so it is reliable; with several, check what ``submit``
returns.
The future of a task that ran is resolved after its slot is free, so ``status`` right after a ``wait`` already counts
it. A task cancelled with ``future.cancel()`` while it is still queued gives its slot back at once.

``submit`` takes an optional ``replace_key``, which is never passed to the task. A task still waiting in the same pool
under the same ``replace_key`` is replaced by the new one, which takes its place in the queue and uses no new slot, so
it is accepted even when the pool is full; the old future is cancelled and counted as ``replaced``. A task that already
started is never replaced. Without a ``replace_key`` nothing changes. ``would_accept(pool, replace_key)`` says whether
a ``submit`` with that ``replace_key`` would be accepted now, which ``status(pool).free_slots`` cannot: with a full
pool ``free_slots`` is 0 even when the replacement would be accepted. It is only a hint, because another thread can
change the pool before ``submit`` runs: the return value of ``submit`` is the answer.
``discard(pool, replace_key)`` removes the task still waiting under that ``replace_key``, cancels its future and counts
it as ``canceled``, so a result that nobody needs any more does not take a thread. It returns True if it did, and False
if there is no such task or it already started: a started task is never touched.

Tasks must be short and must not depend on the caller's request or transaction. A task that raises is logged, and the
exception is kept in its future. The pool's threads open their own database connections, which are closed when each task
ends.

``shutdown()`` lets the tasks that are running finish (each bounded by its own request timeouts) and cancels the queued
ones, so whoever waits for them is released. The owner of the process should call it; the scheduler does, in the
``finally`` of its loop. The threads are daemons, so a process that never calls it is not kept alive at exit: tasks
still running are abandoned and queued ones are lost.

Once the pool has threads, ``os.fork()`` in ``api/domain/isolated.py`` runs in a multi-threaded process and Python
3.12 may emit a DeprecationWarning. It is safe there because the child only validates and leaves through
``os._exit``, so do not "fix" the warning by touching connections in the child.

Adopting it in the gateway needs ``init()`` in every gunicorn worker (a process) after the fork (``main/wsgi.py`` is
imported there) and ``shutdown()`` from a ``worker_exit`` hook, for a clean exit. Each process has its own pool, so the
limits multiply by the number of gunicorn workers.

Metrics are published on the default prometheus_client registry, which the gateway (django_prometheus) and the
scheduler already expose. ``background_executor_workers`` is the configured number of threads. Per pool:
``background_executor_max_pending`` (its limit), ``background_executor_pending`` (accepted and unfinished, running
included), ``background_executor_running``, ``background_executor_tasks_total{outcome}`` (completed, failed, canceled
while queued by ``shutdown`` or by the caller, or replaced by a task with the same ``replace_key``),
``background_executor_dropped_total{reason}`` (full, or shut_down for a ``submit`` that races with a ``shutdown``) and
``background_executor_task_duration_seconds``. Compare ``pending`` with ``max_pending`` and watch ``dropped_total`` to
size the pool. Every process reports its own numbers: the gateway has several, so aggregate across them in the query.

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
    ``free_slots`` is how many more new tasks ``submit`` would accept for this pool right now (a ``submit`` with a
    ``replace_key`` that replaces a waiting task needs no slot: ask ``would_accept``), and ``idle_workers`` how many
    threads of the process have nothing to do."""

    queued: int
    running: int
    free_slots: int
    idle_workers: int


class BackgroundPool(Enum):
    """Who is submitting. Add a member for each new caller: the pools split the limit evenly."""

    RUNTIME_API = "runtime_api"  # calls to the Runtime API
    CODE_ENGINE = "code_engine"  # fleet lists and fleet checks of the fleet cleanup


class TaskOutcome(Enum):
    """How a task ended: the ``outcome`` label of ``background_executor_tasks_total``."""

    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"  # while queued, by ``shutdown`` or by the caller
    REPLACED = "replaced"  # while queued, by a task with the same ``replace_key``


class DropReason(Enum):
    """Why ``submit`` did not accept a task: the ``reason`` label of ``background_executor_dropped_total``."""

    FULL = "full"
    SHUT_DOWN = "shut_down"


_WORKERS = Gauge("background_executor_workers", "Configured number of threads of this process.")
_MAX_PENDING = Gauge(
    "background_executor_max_pending", "Limit of accepted and unfinished tasks of the pool.", labelnames=("pool",)
)
_PENDING = Gauge(
    "background_executor_pending",
    "Tasks accepted and not finished yet, running ones included.",
    labelnames=("pool",),
)
_RUNNING = Gauge("background_executor_running", "Tasks running on a thread right now.", labelnames=("pool",))
_TASKS = Counter("background_executor_tasks_total", "Finished tasks by outcome.", labelnames=("pool", "outcome"))
_DROPPED = Counter("background_executor_dropped_total", "Tasks that were not accepted.", labelnames=("pool", "reason"))
_DURATION = Histogram(
    "background_executor_task_duration_seconds", "Run time of one background task.", labelnames=("pool",)
)


def _nothing() -> None:
    """What a released task holds in place of its function."""


class _Task:
    """A task accepted by ``submit``. ``replaced`` is set, under the lock of the cycle, when a newer task took its place
    in the queue: its done callback then has nothing to do."""

    __slots__ = ("future", "fn", "args", "kwargs", "replace_key", "replaced")

    def __init__(self, fn: Callable, args: tuple, kwargs: dict, replace_key: str | None) -> None:
        self.future: Future = Future()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.replace_key = replace_key
        self.replaced = False

    def release(self) -> None:
        """Let go of what it was going to run, which can be large: the done callback keeps the task alive for as long
        as the caller keeps the future."""
        self.fn, self.args, self.kwargs = _nothing, (), {}

    def replace(self) -> None:
        """Mark it as replaced, so its done callback has nothing to do, and release it."""
        self.replaced = True
        self.release()


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

    def forget_if_cancelled(self, pool: BackgroundPool, task: _Task) -> None:
        """Done callback of a queued task: if the caller cancelled it, take it out of the queue now, so its slot is free
        and whoever waits for it is released. A thread that already took it accounts for it by itself, and a task that
        was replaced is accounted for by the ``submit`` that replaced it."""
        if not task.future.cancelled():
            return
        with self.cond:
            if task.replaced:
                return
            try:
                self.queues[pool].remove(task)
            except ValueError:
                return
            _TASKS.labels(pool.value, TaskOutcome.CANCELED.value).inc()
            _PENDING.labels(pool.value).dec()
        task.release()
        task.future.set_running_or_notify_cancel()  # wakes whoever waits for it

    def waiting_index(self, pool: BackgroundPool, replace_key: str) -> int | None:
        """Position in the queue of ``pool`` of the task waiting under ``replace_key``, or None. Call it with ``cond``
        held."""
        for index, task in enumerate(self.queues[pool]):
            if task.replace_key == replace_key:
                return index
        return None

    def enqueue(self, pool: BackgroundPool, task: _Task) -> tuple[DropReason | None, _Task | None]:
        """Accept ``task`` or say why not. Returns ``(drop reason, None)`` when it is dropped, otherwise
        ``(None, the task it replaced or None)``. Call it with ``cond`` held."""
        if self.stopping:
            return DropReason.SHUT_DOWN, None
        index = None if task.replace_key is None else self.waiting_index(pool, task.replace_key)
        if index is not None:  # same position and same slot, so _PENDING does not change
            old = self.queues[pool][index]
            self.queues[pool][index] = task
            old.replace()
            # one the caller had already cancelled (its callback is still waiting for the lock) counts as canceled
            outcome = TaskOutcome.CANCELED if old.future.cancelled() else TaskOutcome.REPLACED
            _TASKS.labels(pool.value, outcome.value).inc()
            return None, old
        if self.pending(pool) >= self.pool_limit:
            return DropReason.FULL, None
        self.queues[pool].append(task)
        _PENDING.labels(pool.value).inc()
        self.cond.notify()
        return None, None

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
                task = self.queues[pool].popleft()
                self.running[pool] += 1
                self.clock += 1
                self.served[pool] = self.clock
            try:
                self._execute(pool, task.future, task.fn, task.args, task.kwargs)
            except Exception:  # pylint: disable=broad-exception-caught
                logger.exception("background thread failed while finishing a task")  # keep the thread alive
            finally:
                task.release()

    def _execute(self, pool: BackgroundPool, future: Future, fn: Callable, args: tuple, kwargs: dict) -> None:
        if future.cancelled():  # cancelled just after a thread took it: free the slot, then wake the waiters
            try:
                self._finish(pool, TaskOutcome.CANCELED)
            finally:
                future.set_running_or_notify_cancel()
            return
        if not future.set_running_or_notify_cancel():  # cancelled in the instant between the two calls
            self._finish(pool, TaskOutcome.CANCELED)
            return
        result, error, outcome = None, None, TaskOutcome.COMPLETED
        _RUNNING.labels(pool.value).inc()
        started = time.monotonic()
        try:
            result = fn(*args, **kwargs)
        except BaseException as exc:  # pylint: disable=broad-exception-caught
            error, outcome = exc, TaskOutcome.FAILED
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

    def _finish(self, pool: BackgroundPool, outcome: TaskOutcome) -> None:
        try:
            _TASKS.labels(pool.value, outcome.value).inc()
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

    def submit(
        self, pool: BackgroundPool, fn: Callable, *args, replace_key: str | None = None, **kwargs
    ) -> Future | None:
        """Run ``fn(*args, **kwargs)`` on a thread and return at once with its ``Future``. Returns None, without
        running it, when the ``pool`` already has its share of tasks pending and the task does not replace a waiting
        one, or when the executor is shutting down. Raises BackgroundExecutorNotInitializedError if ``init`` was not
        called in this process.

        ``replace_key`` is reserved: it is never passed to ``fn``. If a task of the same ``pool`` and ``replace_key`` is
        still waiting, the new one takes its place in the queue and the old future is cancelled: no new slot is used, so
        it is accepted even when the pool is full. A task that already started is never replaced."""
        cycle = self._current_cycle()
        task = _Task(fn, args, kwargs, replace_key)
        with cycle.cond:
            reason, replaced = cycle.enqueue(pool, task)
            if reason is None:  # under the lock, so a shutdown cannot cancel it before the callback is in place
                task.future.add_done_callback(lambda _future: cycle.forget_if_cancelled(pool, task))
        if reason is not None:
            _DROPPED.labels(pool.value, reason.value).inc()
            logger.warning("background pool %s is %s, task dropped", pool.value, reason.value.replace("_", " "))
            return None
        if replaced is not None:  # its done callback skips it, so release whoever waits for it here
            replaced.future.cancel()
            replaced.future.set_running_or_notify_cancel()
        return task.future

    def would_accept(self, pool: BackgroundPool, replace_key: str | None = None) -> bool:
        """True if ``submit(pool, ..., replace_key=replace_key)`` would be accepted right now: the pool is below its
        limit, or a task with that ``replace_key`` is waiting in it and would be replaced. Only a hint, because another
        thread can change the pool before ``submit`` runs: check what ``submit`` returns. Raises
        BackgroundExecutorNotInitializedError if ``init`` was not called in this process."""
        cycle = self._current_cycle()
        with cycle.cond:
            if cycle.stopping:
                return False
            return cycle.pending(pool) < cycle.pool_limit or (
                replace_key is not None and cycle.waiting_index(pool, replace_key) is not None
            )

    def discard(self, pool: BackgroundPool, replace_key: str) -> bool:
        """Cancel the task of ``pool`` still waiting under ``replace_key``. Its slot is free at once and whoever waits
        for its future is released. Returns False when none is waiting, and a task that already started is never
        touched. Raises BackgroundExecutorNotInitializedError if ``init`` was not called in this process."""
        cycle = self._current_cycle()
        with cycle.cond:  # a thread takes a task under this lock, so it either runs it or it is discarded here
            index = cycle.waiting_index(pool, replace_key)
            if index is None:
                return False
            return cycle.queues[pool][index].future.cancel()  # its done callback removes it and counts it as canceled

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
                    for task in list(queue):
                        task.future.cancel()  # its done callback takes it out of the queue and counts it as canceled
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
