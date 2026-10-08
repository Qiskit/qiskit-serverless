"""One shared thread pool per process for best-effort work: tasks whose result nobody waits for.

Every caller in a process shares the same pool, so the total number of background threads stays bounded by
``settings.BEST_EFFORT_MAX_WORKERS``. Processes cannot share a pool, so each one (and each forked child, for example a
gunicorn worker) builds its own. At most ``settings.BEST_EFFORT_MAX_PENDING`` tasks can be submitted and unfinished at
once; the next one is dropped and ``submit_best_effort`` returns False. Dropping is by design: this is not a queue.

Tasks must be short and must not depend on the caller's request or transaction. A task that raises is logged and
forgotten. Worker threads open their own database connections, which are closed when each task ends.

The Kafka best-effort sender could adopt this pool later.
"""

import atexit
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from django.conf import settings
from django.db import connections

logger = logging.getLogger("gateway.best_effort")


class _State:  # pylint: disable=too-few-public-methods
    """The pool of this process and the counters around it."""

    lock = threading.Lock()
    executor: ThreadPoolExecutor | None = None
    slots: threading.BoundedSemaphore | None = None
    pid: int | None = None
    dropped = 0


def _pool() -> tuple[ThreadPoolExecutor, threading.BoundedSemaphore]:
    """The pool of this process, created on first use. A forked child must not reuse its parent's threads."""
    with _State.lock:
        if _State.executor is None or _State.pid != os.getpid():
            _State.executor = ThreadPoolExecutor(
                max_workers=settings.BEST_EFFORT_MAX_WORKERS, thread_name_prefix="best-effort"
            )
            _State.slots = threading.BoundedSemaphore(settings.BEST_EFFORT_MAX_PENDING)
            _State.pid = os.getpid()
        return _State.executor, _State.slots


def submit_best_effort(fn: Callable, *args, **kwargs) -> bool:
    """Run ``fn(*args, **kwargs)`` on the shared pool and return at once. Returns False, without running it, when too
    many tasks are already pending."""
    executor, slots = _pool()
    if not slots.acquire(blocking=False):  # pylint: disable=consider-using-with
        _State.dropped += 1
        logger.warning("best effort pool is full, task dropped (%s dropped so far)", _State.dropped)
        return False

    def run() -> None:
        try:
            fn(*args, **kwargs)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.warning("best effort task %s failed: %r", getattr(fn, "__qualname__", fn), exc)
        finally:
            connections.close_all()
            slots.release()

    try:
        executor.submit(run)
    except RuntimeError:  # the executor was shut down between _pool() and here
        slots.release()
        logger.warning("best effort pool is shut down, task dropped")
        return False
    return True


def shutdown_best_effort_executor() -> None:
    """Stop the pool of this process: running tasks finish (each ends within its own timeouts), pending ones are
    cancelled. Safe to call twice or with no pool; a later ``submit_best_effort`` creates a new one."""
    with _State.lock:
        executor, owner = _State.executor, _State.pid
        _State.executor, _State.slots, _State.pid = None, None, None
    if executor is not None and owner == os.getpid():
        executor.shutdown(wait=True, cancel_futures=True)


atexit.register(shutdown_best_effort_executor)
