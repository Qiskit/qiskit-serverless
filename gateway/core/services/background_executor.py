"""One shared thread pool per process for background work: tasks whose result nobody waits for.

Call ``BackgroundExecutor.init()`` once at startup, in every process that uses it (the scheduler in
``scheduler/main.py``, the gateway workers in a later change). ``submit`` fails loudly with
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

The Kafka sender could adopt this pool later.
"""

import atexit
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from django.conf import settings
from django.db import connections

logger = logging.getLogger("core.BackgroundExecutor")


class BackgroundExecutorNotInitializedError(RuntimeError):
    """``BackgroundExecutor.submit`` was called before ``init``, or in a process other than the one that called it."""


class _State:  # pylint: disable=too-few-public-methods
    """The pool of this process and the counters around it."""

    lock = threading.Lock()
    executor: ThreadPoolExecutor | None = None
    slots: threading.BoundedSemaphore | None = None
    pid: int | None = None
    dropped = 0
    closing = False  # set when the interpreter starts to exit; queued tasks then skip their work


class BackgroundExecutor:
    """The process-wide pool, kept as class state. Use the classmethods; there are no instances."""

    @classmethod
    def init(cls, max_workers: int | None = None, max_pending: int | None = None) -> None:
        """Create the pool of this process. The limits default to ``settings.BACKGROUND_EXECUTOR_MAX_WORKERS`` and
        ``settings.BACKGROUND_EXECUTOR_MAX_PENDING``. Raises RuntimeError if this process already has a pool, unless
        ``shutdown`` was called in between."""
        with _State.lock:
            if _State.executor is not None and _State.pid == os.getpid():
                raise RuntimeError("BackgroundExecutor is already initialized in this process")
            workers = settings.BACKGROUND_EXECUTOR_MAX_WORKERS if max_workers is None else max_workers
            pending = settings.BACKGROUND_EXECUTOR_MAX_PENDING if max_pending is None else max_pending
            _State.executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="background")
            _State.slots = threading.BoundedSemaphore(pending)
            _State.pid = os.getpid()

    @classmethod
    def submit(cls, fn: Callable, *args, **kwargs) -> bool:
        """Run ``fn(*args, **kwargs)`` on the pool and return at once. Returns False, without running it, when too
        many tasks are already pending. Raises BackgroundExecutorNotInitializedError if ``init`` was not called in
        this process."""
        with _State.lock:
            executor, slots, owner = _State.executor, _State.slots, _State.pid
        if executor is None or owner != os.getpid():
            raise BackgroundExecutorNotInitializedError("BackgroundExecutor.init() was not called in this process")

        if not slots.acquire(blocking=False):  # pylint: disable=consider-using-with
            with _State.lock:
                _State.dropped += 1
                dropped = _State.dropped
            logger.warning("background pool is full, task dropped (%s dropped so far)", dropped)
            return False

        def run() -> None:
            try:
                if _State.closing:
                    return
                fn(*args, **kwargs)
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logger.warning("background task %s failed: %r", getattr(fn, "__qualname__", fn), exc)
            finally:
                connections.close_all()
                slots.release()

        try:
            executor.submit(run)
        except RuntimeError:  # the executor was shut down after the check above
            slots.release()
            logger.warning("background pool is shut down, task dropped")
            return False
        return True

    @classmethod
    def shutdown(cls) -> None:
        """Stop the pool of this process: running tasks finish (each ends within its own timeouts), pending ones are
        cancelled. It does not set the exit flag. Safe to call twice or when never initialized; ``init`` can be called
        again afterwards."""
        with _State.lock:
            executor, owner = _State.executor, _State.pid
            _State.executor, _State.slots, _State.pid = None, None, None
        if executor is not None and owner == os.getpid():
            executor.shutdown(wait=True, cancel_futures=True)


def _start_closing() -> None:
    _State.closing = True


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

atexit.register(BackgroundExecutor.shutdown)
