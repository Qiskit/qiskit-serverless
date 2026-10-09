"""One shared thread pool per process for background work: tasks whose result nobody waits for.

There is a single ``BackgroundExecutor`` per process; get it with ``get_background_executor()``. Call ``init()`` on it
once at startup, in every process that uses it (the scheduler in ``scheduler/main.py``, the gateway workers in a later
change). ``submit`` fails loudly with
``BackgroundExecutorNotInitializedError`` if ``init`` was not called, or if the pool belongs to another process: a
forked child inherits the class state but not the threads, so it must call ``init`` again.

Every caller in a process shares the same pool, so the total number of background threads stays bounded by
``settings.BACKGROUND_EXECUTOR_MAX_WORKERS``. At most ``settings.BACKGROUND_EXECUTOR_MAX_PENDING`` tasks can be
submitted and unfinished at once; the next one is dropped and ``submit`` returns False. Dropping is by design: this is
not a queue.

Tasks must be short and must not depend on the caller's request or transaction. A task that raises is logged and
forgotten. Worker threads open their own database connections, which are closed when each task ends.

At interpreter exit, tasks still queued are skipped and only the ones already running finish, each bounded by its own
request timeouts (about 2 x workloads.mirror.timeout_ms for a workload mirror call). Nothing is cancelled and nothing
is promised.

Once the pool has threads, ``os.fork()`` in ``api/domain/isolated.py`` runs in a multi-threaded process and Python
3.12 may emit a DeprecationWarning. It is safe there because the child only validates and leaves through
``os._exit``, so do not "fix" the warning by touching connections in the child.

Metrics are published on the default prometheus_client registry, which the gateway (django_prometheus) and the
scheduler already expose: ``background_executor_workers`` and ``background_executor_max_pending`` (the configured
limits), ``background_executor_pending`` (accepted and unfinished, running included), ``background_executor_running``,
``background_executor_tasks_total{outcome}`` (completed, failed or skipped at exit),
``background_executor_dropped_total{reason}`` (full or shut_down) and ``background_executor_task_duration_seconds``.
Compare ``pending`` with ``max_pending`` and watch ``dropped_total`` to size the pool. Every process reports its own
numbers: the gateway has several, so aggregate across them in the query.

The Kafka sender could adopt this pool later.
"""

import atexit
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from django.conf import settings
from django.db import connections
from prometheus_client import Counter, Gauge, Histogram

logger = logging.getLogger("core.BackgroundExecutor")


class BackgroundExecutorNotInitializedError(RuntimeError):
    """``BackgroundExecutor.submit`` was called before ``init``, or in a process other than the one that called it."""


_WORKERS = Gauge("background_executor_workers", "Configured number of worker threads of this process.")
_MAX_PENDING = Gauge("background_executor_max_pending", "Configured limit of accepted and unfinished tasks.")
_PENDING = Gauge("background_executor_pending", "Tasks accepted and not finished yet, running ones included.")
_RUNNING = Gauge("background_executor_running", "Tasks running on a worker thread right now.")
_TASKS = Counter("background_executor_tasks_total", "Finished tasks by outcome.", labelnames=("outcome",))
_DROPPED = Counter("background_executor_dropped_total", "Tasks that were not accepted.", labelnames=("reason",))
_DURATION = Histogram("background_executor_task_duration_seconds", "Run time of one background task.")


class BackgroundExecutor:  # pylint: disable=too-many-instance-attributes
    """The pool of this process. Do not build it: use ``get_background_executor()``."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._executor: ThreadPoolExecutor | None = None
        self._slots: threading.BoundedSemaphore | None = None
        self._pid: int | None = None
        self.max_workers = 0
        self.max_pending = 0
        self.dropped = 0
        self.closing = False  # set when the interpreter starts to exit; queued tasks then skip their work

    def init(self, max_workers: int | None = None, max_pending: int | None = None) -> None:
        """Create the pool of this process. The limits default to ``settings.BACKGROUND_EXECUTOR_MAX_WORKERS`` and
        ``settings.BACKGROUND_EXECUTOR_MAX_PENDING``. Raises RuntimeError if this process already has a pool, unless
        ``shutdown`` was called in between."""
        with self._lock:
            if self._executor is not None and self._pid == os.getpid():
                raise RuntimeError("BackgroundExecutor is already initialized in this process")
            self.max_workers = settings.BACKGROUND_EXECUTOR_MAX_WORKERS if max_workers is None else max_workers
            self.max_pending = settings.BACKGROUND_EXECUTOR_MAX_PENDING if max_pending is None else max_pending
            self._executor = ThreadPoolExecutor(max_workers=self.max_workers, thread_name_prefix="background")
            self._slots = threading.BoundedSemaphore(self.max_pending)
            self._pid = os.getpid()
            _WORKERS.set(self.max_workers)
            _MAX_PENDING.set(self.max_pending)
            _PENDING.set(0)
            _RUNNING.set(0)

    def submit(self, fn: Callable, *args, **kwargs) -> bool:
        """Run ``fn(*args, **kwargs)`` on the pool and return at once. Returns False, without running it, when too
        many tasks are already pending. Raises BackgroundExecutorNotInitializedError if ``init`` was not called in
        this process."""
        with self._lock:
            executor, slots, owner = self._executor, self._slots, self._pid
        if executor is None or owner != os.getpid():
            raise BackgroundExecutorNotInitializedError("BackgroundExecutor.init() was not called in this process")

        if not slots.acquire(blocking=False):  # pylint: disable=consider-using-with
            with self._lock:
                self.dropped += 1
                dropped = self.dropped
            _DROPPED.labels("full").inc()
            logger.warning("background pool is full, task dropped (%s dropped so far)", dropped)
            return False

        def run() -> None:
            outcome = "completed"
            try:
                if self.closing:
                    outcome = "skipped"
                    return
                _RUNNING.inc()
                started = time.monotonic()
                try:
                    fn(*args, **kwargs)
                finally:
                    _RUNNING.dec()
                    _DURATION.observe(time.monotonic() - started)
            except Exception as exc:  # pylint: disable=broad-exception-caught
                outcome = "failed"
                logger.warning("background task %s failed: %r", getattr(fn, "__qualname__", fn), exc)
            finally:
                _TASKS.labels(outcome).inc()
                _PENDING.dec()
                connections.close_all()
                slots.release()

        _PENDING.inc()
        try:
            executor.submit(run)
        except RuntimeError:  # the executor was shut down after the check above
            _PENDING.dec()
            slots.release()
            _DROPPED.labels("shut_down").inc()
            logger.warning("background pool is shut down, task dropped")
            return False
        return True

    def shutdown(self) -> None:
        """Stop the pool of this process: running tasks finish (each ends within its own timeouts), pending ones are
        cancelled. It does not set the exit flag. Safe to call twice or when never initialized; ``init`` can be called
        again afterwards."""
        with self._lock:
            executor, owner = self._executor, self._pid
            self._executor, self._slots, self._pid = None, None, None
        if executor is not None and owner == os.getpid():
            executor.shutdown(wait=True, cancel_futures=True)


_instance = BackgroundExecutor()


def get_background_executor() -> BackgroundExecutor:
    """The one ``BackgroundExecutor`` of this process. It still needs ``init()`` before ``submit``."""
    return _instance


def _start_closing() -> None:
    _instance.closing = True


# concurrent.futures.thread registers its own exit hook with threading._register_atexit when it is imported. These
# hooks run in reverse registration order in threading._shutdown(), before the regular atexit callbacks, and that hook
# waits for every queued task. Registering ours here, after that import, makes it run first, so queued tasks can skip
# their work and the drain is bounded by the tasks already running. It is a private API: if it is missing (a future
# Python) or shutdown has already begun, we only lose the early skip and the drain is bounded by the pending tasks.
_register_atexit = getattr(threading, "_register_atexit", None)
if _register_atexit is not None:
    try:
        _register_atexit(_start_closing)
    except RuntimeError:
        pass

atexit.register(_instance.shutdown)
