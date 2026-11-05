"""Signal handling for the scheduler loops."""

import signal
import threading

import logging

logger = logging.getLogger("scheduler.kill_signal")

# How long a waiter sleeps before it looks at the flag again. It bounds how late a signal is noticed.
POLL_SECONDS = 0.1


class KillSignal:
    """Encapsulates signal handling for graceful shutdown.

    The signal handler runs on the main thread, between two bytecodes of whatever that thread was doing, so it must not
    take a lock: if the main thread already held it, the handler would wait for itself for ever. That is why the handler
    only sets a plain flag. Waiters sleep in short slices on a private Event nobody sets, and look at the flag after
    each one, so a stop is noticed within POLL_SECONDS. ``received`` can also be set from any thread, which wakes the
    sleepers at once, since that setter is never called from the handler.
    """

    def __init__(self):
        self._received = False
        self._wakeup = threading.Event()

    @property
    def received(self) -> bool:
        """Whether a stop was requested."""
        return self._received

    @received.setter
    def received(self, value: bool) -> None:
        self._received = value
        if value:
            self._wakeup.set()
        else:
            self._wakeup.clear()

    def wait(self, timeout: float) -> bool:
        """Sleep up to ``timeout`` seconds, or less if a stop is requested. Returns whether it was requested."""
        remaining = timeout
        while remaining > 0 and not self._received:
            slice_seconds = min(POLL_SECONDS, remaining)
            self._wakeup.wait(slice_seconds)
            remaining -= slice_seconds
        return self._received

    def register(self):
        """Register signal handlers for graceful shutdown. Python only allows it from the main thread."""
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

    def _handle_signal(self, signum, _frame):
        logger.info("Received signal %s, stopping scheduler loops...", signum)
        # Only the flag: no lock may be taken here, see the class docstring
        self._received = True
