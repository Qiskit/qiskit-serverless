"""In-memory circuit breaker for a scheduler task's outbound sends.

Not persisted: a process restart resets it to closed. The scheduler is single-threaded (one instance
per task, used only from the main loop), so no locking is needed here.
"""

import time


class CircuitBreaker:
    """Opens after N consecutive failures; reports closed again once a pause elapses."""

    def __init__(self, failure_threshold: int, pause_seconds: float):
        self._failure_threshold = failure_threshold
        self._pause_seconds = pause_seconds
        self._consecutive_failures = 0
        self._opened_at: float | None = None

    @property
    def is_open(self) -> bool:
        """Whether sends should currently be skipped."""
        if self._opened_at is None:
            return False
        if time.monotonic() - self._opened_at >= self._pause_seconds:
            self._reset()
            return False
        return True

    def record_success(self) -> None:
        """Reset the failure streak after a successful send."""
        self._consecutive_failures = 0

    def record_failure(self) -> None:
        """Count one failed send, opening the breaker once the threshold is reached."""
        self._consecutive_failures += 1
        if self._consecutive_failures >= self._failure_threshold and self._opened_at is None:
            self._opened_at = time.monotonic()

    def _reset(self) -> None:
        self._consecutive_failures = 0
        self._opened_at = None
