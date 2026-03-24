"""Shared health state between the scheduler loop and the HTTP probe."""

import threading

from django.db.utils import InterfaceError, OperationalError

DB_EXCEPTIONS = (OperationalError, InterfaceError)

# Must be consistent with the livenessProbe failureThreshold in deployment.yaml.
# Kubernetes restarts the pod after (failureThreshold * periodSeconds) seconds of
# unhealthy responses. Keep this threshold low enough to trigger before that window.
UNHEALTHY_THRESHOLD = 5


class SchedulerHealth:
    """Tracks consecutive DB errors to determine scheduler liveness."""

    def __init__(self):
        self._consecutive_errors: int = 0
        # Not strictly necessary in CPython because the GIL makes simple integer
        # reads and writes atomic, but keeps the code correct on other runtimes.
        self._lock = threading.Lock()

    def set_db_error(self) -> bool:
        """Increment the consecutive-error counter. Returns True on the first error in a streak."""
        with self._lock:
            self._consecutive_errors += 1
            return self._consecutive_errors == 1

    def clear_db_error(self) -> None:
        """Reset the consecutive-error counter after a successful task run."""
        with self._lock:
            self._consecutive_errors = 0

    @property
    def is_unhealthy(self) -> bool:
        """Return True if consecutive DB errors have reached the unhealthy threshold."""
        with self._lock:
            return self._consecutive_errors >= UNHEALTHY_THRESHOLD
