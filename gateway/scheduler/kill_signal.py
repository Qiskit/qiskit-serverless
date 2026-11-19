"""Signal handling for the scheduler loops."""

import logging
import signal
import time

logger = logging.getLogger("scheduler.kill_signal")

# How long a waiter sleeps before it looks at the flag again. It bounds how late a stop is noticed.
POLL_SECONDS = 0.1


class KillSignal:
    """Encapsulates signal handling for graceful shutdown.

    The signal handler runs on the main thread, between two bytecodes of whatever that thread was doing, so it must not
    take a lock: if the main thread already held it, the handler would wait for itself for ever. That is why the handler
    only sets a plain flag, and why the waiters do not block on an Event (setting one takes a lock): they sleep in short
    slices and look at the flag after each one, so a stop is noticed within POLL_SECONDS.
    """

    def __init__(self):
        self.received = False

    def wait(self, timeout: float) -> bool:
        """Sleep up to ``timeout`` seconds, or less if a stop is requested. Returns whether it was requested."""
        deadline = time.monotonic() + timeout
        while not self.received:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(POLL_SECONDS, remaining))
        return self.received

    def register(self):
        """Register signal handlers for graceful shutdown. Python only allows it from the main thread."""
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

    def _handle_signal(self, signum, _frame):
        logger.info("Received signal %s, stopping scheduler loops...", signum)
        # Only the flag: no lock may be taken here, see the class docstring
        self.received = True
