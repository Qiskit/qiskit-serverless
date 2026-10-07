"""In-memory circuit breaker for a scheduler task's outbound sends.

Not persisted: a process restart resets it to closed. The scheduler is single-threaded (one instance
per task, used only from the main loop), so no locking is needed here.
"""

import time

from core.config_key import ConfigKey
from core.models import Config

DEFAULT_FAILURE_THRESHOLD = 5
DEFAULT_PAUSE_SECONDS = 60


class CircuitBreaker:
    """Opens after N consecutive failures; reports closed again once a pause elapses, with the failure streak
    back at zero, so it takes a whole new streak to open it again.

    The failure threshold and the pause are the Config entries `failure_threshold_key` and `pause_seconds_key`,
    read every time they are needed, so they can change at runtime without recreating the breaker or
    restarting the process.
    """

    def __init__(self, failure_threshold_key: ConfigKey, pause_seconds_key: ConfigKey):
        self._failure_threshold_key = failure_threshold_key
        self._pause_seconds_key = pause_seconds_key
        self._consecutive_failures = 0
        self._opened_at: float | None = None

    @property
    def is_open(self) -> bool:
        """Whether sends should currently be skipped."""
        if self._opened_at is None:
            return False
        if time.monotonic() - self._opened_at >= self._pause_seconds():
            self._reset()
            return False
        return True

    def record_success(self) -> None:
        """Reset the failure streak after a successful send."""
        self._consecutive_failures = 0

    def record_failure(self) -> None:
        """Count one failed send, opening the breaker once the threshold is reached."""
        self._consecutive_failures += 1
        if self._consecutive_failures >= self._failure_threshold() and self._opened_at is None:
            self._opened_at = time.monotonic()

    def _failure_threshold(self) -> int:
        return Config.get_int(self._failure_threshold_key, default=DEFAULT_FAILURE_THRESHOLD)

    def _pause_seconds(self) -> int:
        return Config.get_int(self._pause_seconds_key, default=DEFAULT_PAUSE_SECONDS)

    def _reset(self) -> None:
        self._consecutive_failures = 0
        self._opened_at = None
