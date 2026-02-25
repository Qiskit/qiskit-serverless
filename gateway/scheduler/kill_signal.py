import signal

import logging

logger = logging.getLogger("kill_signal")


class KillSignal:
    """Encapsulates signal handling and the running flag for graceful shutdown."""

    def __init__(self):
        self.running = True

    def register(self):
        """Register signal handlers for graceful shutdown."""
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

    def _handle_signal(self, signum, _frame):
        logger.info("Received signal %s, stopping scheduler loop...", signum)
        self.running = False
