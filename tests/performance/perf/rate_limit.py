"""A token bucket like the client-go rate limiter: up to `burst` at once, then `qps` per second."""

import threading
import time


class RateLimiter:  # pylint: disable=too-few-public-methods
    """Starts full with `burst` tokens and refills at `qps` tokens per second, up to `burst`."""

    def __init__(self, qps: float, burst: int):
        self._qps = qps
        self._burst = burst
        self._tokens = float(burst)
        self._last = time.monotonic()
        self._lock = threading.Lock()

    def wait(self, stop: threading.Event) -> bool:
        """Take one token, waiting for it if needed. False when stop is set first."""
        while True:
            with self._lock:
                now = time.monotonic()
                self._tokens = min(self._burst, self._tokens + (now - self._last) * self._qps)
                self._last = now
                if self._tokens >= 1:
                    self._tokens -= 1
                    return True
                wait = (1 - self._tokens) / self._qps
            if stop.wait(wait):
                return False
