"""One shared thread pool per process for background work: tasks whose result nobody waits for.

There is a single ``BackgroundExecutor`` per process; get it with ``get_background_executor()``. Call ``init()`` on it
once at startup, in every process that uses it (the scheduler in ``scheduler/main.py``). ``submit`` fails loudly with
``BackgroundExecutorNotInitializedError`` if ``init`` was not called, or if the pool belongs to another process: a
forked child inherits the class state but not the threads, so it must call ``init`` again.

Every caller in a process shares the same threads, so the total number of background threads stays bounded by
``settings.BACKGROUND_EXECUTOR_MAX_WORKERS``. At most ``settings.BACKGROUND_EXECUTOR_MAX_PENDING`` tasks can be
submitted and unfinished at once; the next one is dropped and ``submit`` returns False. Dropping is by design: this is
not a queue.

Each caller submits under a ``BackgroundPool`` name, so a slow service cannot take every slot from the others. A pool
always gets its own minimum number of slots (``_MIN_SHARE`` of ``MAX_PENDING``), even when the global limit is full.
It has no maximum: when the others are idle it can use the whole ``MAX_PENDING``. So the guaranteed slots are on top of
the global limit, and the most that can be pending is ``MAX_PENDING`` plus the minimums of the pools that are under
theirs. The guarantee is about slots, not threads: tasks wait for a thread in arrival order, so a slow service delays
the others but cannot make them drop work.

Tasks must be short and must not depend on the caller's request or transaction. A task that raises is logged and
forgotten. Worker threads open their own database connections, which are closed when each task ends.

``shutdown()`` lets the tasks that are running finish (each bounded by its own request timeouts) and cancels the
queued ones. The owner of the process must call it. The scheduler does, in the ``finally`` of its loop. There is no
exit hook on purpose: without a ``shutdown()`` the interpreter waits for every queued task before exiting. A process
that cannot call it from its own shutdown path (the gateway, under gunicorn) needs a hook for that when it adopts
this pool, because it would otherwise wait for up to ``MAX_PENDING`` queued tasks at exit.

Once the pool has threads, ``os.fork()`` in ``api/domain/isolated.py`` runs in a multi-threaded process and Python
3.12 may emit a DeprecationWarning. It is safe there because the child only validates and leaves through
``os._exit``, so do not "fix" the warning by touching connections in the child.

Metrics are published on the default prometheus_client registry, which the gateway (django_prometheus) and the
scheduler already expose: ``background_executor_workers`` and ``background_executor_max_pending`` (the configured
limits), and per pool ``background_executor_pending`` (accepted and unfinished, running included),
``background_executor_running``, ``background_executor_tasks_total{outcome}`` (completed, failed or skipped at
shutdown), ``background_executor_dropped_total{reason}`` (full or shut_down) and
``background_executor_task_duration_seconds``. Compare ``pending`` with ``max_pending`` and watch ``dropped_total`` to
size the pool. Every process reports its own numbers: the gateway has several, so aggregate across them in the query.

The Kafka sender could adopt this pool later.
"""

import logging
import os
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from enum import Enum
from typing import Callable

from django.conf import settings
from django.db import connections
from prometheus_client import Counter, Gauge, Histogram

logger = logging.getLogger("core.BackgroundExecutor")


class BackgroundExecutorNotInitializedError(RuntimeError):
    """``BackgroundExecutor.submit`` was called before ``init``, or in a process other than the one that called it."""


class BackgroundPool(Enum):
    """Who is submitting. Add a member for each new caller, and give it a share in ``_MIN_SHARE``."""

    RUNTIME_API = "runtime_api"  # calls to the Runtime API


# Fraction of BACKGROUND_EXECUTOR_MAX_PENDING that each pool can always use, whatever the others are doing. It is a
# minimum, not a limit.
_MIN_SHARE = {BackgroundPool.RUNTIME_API: 0.25}

_WORKERS = Gauge("background_executor_workers", "Configured number of worker threads of this process.")
_MAX_PENDING = Gauge("background_executor_max_pending", "Configured limit of accepted and unfinished tasks.")
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


class BackgroundExecutor:  # pylint: disable=too-many-instance-attributes
    """The pool of this process. Do not build it: use ``get_background_executor()``."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._executor: ThreadPoolExecutor | None = None
        self._pid: int | None = None
        self._pending: dict[BackgroundPool, int] = {}  # accepted and unfinished, per pool
        self._reserved: dict[BackgroundPool, int] = {}  # slots each pool is guaranteed
        self._futures: dict[Future, BackgroundPool] = {}  # accepted tasks not finished, to account for cancelled ones
        self.max_workers = 0
        self.max_pending = 0

    def init(self, max_workers: int | None = None, max_pending: int | None = None) -> None:
        """Create the pool of this process. The limits default to ``settings.BACKGROUND_EXECUTOR_MAX_WORKERS`` and
        ``settings.BACKGROUND_EXECUTOR_MAX_PENDING``. Raises RuntimeError if this process already has a pool, unless
        ``shutdown`` was called in between."""
        with self._lock:
            if self._executor is not None and self._pid == os.getpid():
                raise RuntimeError("BackgroundExecutor is already initialized in this process")
            workers = settings.BACKGROUND_EXECUTOR_MAX_WORKERS if max_workers is None else max_workers
            pending = settings.BACKGROUND_EXECUTOR_MAX_PENDING if max_pending is None else max_pending
            if pending < 0:  # validate before anything is stored
                raise ValueError("max_pending must not be negative")
            executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="background")
            self.max_workers, self.max_pending = workers, pending
            self._executor, self._pid = executor, os.getpid()
            self._pending = {pool: 0 for pool in BackgroundPool}
            self._reserved = {pool: int(pending * _MIN_SHARE[pool]) for pool in BackgroundPool}
            self._futures = {}
            _WORKERS.set(workers)
            _MAX_PENDING.set(pending)
            for pool in BackgroundPool:
                _PENDING.labels(pool.value).set(0)
                _RUNNING.labels(pool.value).set(0)

    def submit(self, pool: BackgroundPool, fn: Callable, *args, **kwargs) -> bool:
        """Run ``fn(*args, **kwargs)`` on the pool and return at once. Returns False, without running it, when the
        slots it may use are taken. Raises BackgroundExecutorNotInitializedError if ``init`` was not called
        in this process."""
        with self._lock:
            executor, owner, pending = self._executor, self._pid, self._pending
            if executor is None or owner != os.getpid():
                raise BackgroundExecutorNotInitializedError("BackgroundExecutor.init() was not called in this process")
            # Its own minimum is always granted; beyond it, the pool competes for the global limit.
            accepted = pending[pool] < self._reserved[pool] or sum(pending.values()) < self.max_pending
            if accepted:
                pending[pool] += 1
        if not accepted:
            _DROPPED.labels(pool.value, "full").inc()
            logger.warning("background pool is full for %s, task dropped", pool.value)
            return False

        def release() -> None:
            with self._lock:
                pending[pool] -= 1

        def run() -> None:
            outcome = "completed"
            try:
                _RUNNING.labels(pool.value).inc()
                started = time.monotonic()
                try:
                    fn(*args, **kwargs)
                finally:
                    _RUNNING.labels(pool.value).dec()
                    _DURATION.labels(pool.value).observe(time.monotonic() - started)
            except Exception as exc:  # pylint: disable=broad-exception-caught
                outcome = "failed"
                logger.warning("background task %s failed: %r", getattr(fn, "__qualname__", fn), exc, exc_info=True)
            finally:
                try:
                    _TASKS.labels(pool.value, outcome).inc()
                    _PENDING.labels(pool.value).dec()
                    connections.close_all()
                finally:
                    release()  # a failing close must not leak the slot

        _PENDING.labels(pool.value).inc()
        try:
            future = executor.submit(run)
            with self._lock:
                self._futures[future] = pool
            future.add_done_callback(self._forget)
        except RuntimeError:  # the executor was shut down after the check above
            _PENDING.labels(pool.value).dec()
            release()
            _DROPPED.labels(pool.value, "shut_down").inc()
            logger.warning("background pool is shut down, task dropped")
            return False
        return True

    def _forget(self, future: Future) -> None:
        with self._lock:
            self._futures.pop(future, None)

    def shutdown(self) -> None:
        """Stop the pool of this process: running tasks finish (each ends within its own timeouts), pending ones are
        cancelled. Safe to call twice or when never initialized; ``init`` can be called again afterwards."""
        with self._lock:
            executor, owner, queued = self._executor, self._pid, dict(self._futures)
            self._executor, self._pid = None, None
        if executor is None or owner != os.getpid():
            return
        # A cancelled task never reaches run(), so count it here as skipped and take it out of the pending gauge.
        for future, pool in queued.items():
            if future.cancel():
                _TASKS.labels(pool.value, "skipped").inc()
                _PENDING.labels(pool.value).dec()
        executor.shutdown(wait=True, cancel_futures=True)


_instance = BackgroundExecutor()


def get_background_executor() -> BackgroundExecutor:
    """The one ``BackgroundExecutor`` of this process. It still needs ``init()`` before ``submit``."""
    return _instance


# There used to be an exit hook here that made queued tasks skip their work, written with the gateway in mind: its
# gunicorn workers have no shutdown path of their own that calls shutdown(). It was removed because nothing uses the
# pool there yet; see the module docstring for what the gateway needs when it does.


def _reset_after_fork() -> None:
    # A thread of the parent may have held the lock at fork time; the child's copy would stay locked forever.
    _instance._lock = threading.Lock()  # pylint: disable=protected-access


os.register_at_fork(after_in_child=_reset_after_fork)
