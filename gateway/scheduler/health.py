"""Shared health state between the scheduler loops and the HTTP probe."""

import threading

from django.db.utils import InterfaceError, OperationalError

from core.synchronized import synchronized

DB_EXCEPTIONS = (OperationalError, InterfaceError)

# Must be consistent with the livenessProbe failureThreshold in deployment.yaml.
# Kubernetes restarts the pod after (failureThreshold * periodSeconds) seconds of
# unhealthy responses. Keep this threshold low enough to trigger before that window.
UNHEALTHY_THRESHOLD = 5


class SchedulerHealth:
    """Tracks the consecutive DB errors of every loop, and the loops that died, to determine scheduler liveness.

    Each loop has its own streak: a healthy loop must not reset the streak of another one that cannot reach the
    database. The scheduler is unhealthy as soon as any loop is.
    """

    def __init__(self):
        self._consecutive_errors: dict[str, int] = {}
        self._dead_loops: set[str] = set()
        # The loops write and the HTTP probe thread reads
        self._lock = threading.Lock()

    @synchronized
    def set_db_error(self, loop: str) -> bool:
        """Increment the consecutive-error counter of a loop. Returns True on the first error in a streak."""
        self._consecutive_errors[loop] = self._consecutive_errors.get(loop, 0) + 1
        return self._consecutive_errors[loop] == 1

    @synchronized
    def clear_db_error(self, loop: str) -> None:
        """Reset the consecutive-error counter of a loop after a successful task run."""
        self._consecutive_errors[loop] = 0

    @synchronized
    def set_loop_dead(self, loop: str) -> None:
        """Record that the thread of a loop ended on its own. Nothing brings it back, so the pod has to restart."""
        self._dead_loops.add(loop)

    @property
    @synchronized
    def is_unhealthy(self) -> bool:
        """Return True if any loop died or reached the unhealthy threshold of consecutive DB errors."""
        return bool(self._dead_loops) or any(
            errors >= UNHEALTHY_THRESHOLD for errors in self._consecutive_errors.values()
        )
