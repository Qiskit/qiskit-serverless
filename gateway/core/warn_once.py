"""Remember what was already reported, so a condition that repeats on every poll is logged once."""

import threading

from core.synchronized import synchronized


class WarnOnce:
    """A bounded set of keys that were already reported, safe to share between threads.

    The scheduler polls the same jobs over and over, and the scheduler loops run in threads of their own. Asking
    "was this reported?" and then adding the key are two steps, so without the lock two threads could both see a key
    as new and both report it. The set is cleared when it reaches ``limit``, because a scheduler runs for weeks: after
    that, a key that is still failing is reported once more, which is better than growing for ever.
    """

    def __init__(self, limit: int = 10_000):
        self._limit = limit
        self._keys: set[str] = set()
        self._lock = threading.Lock()

    @synchronized
    def first(self, key: str) -> bool:
        """True the first time ``key`` is seen, so the caller reports it. False on every later call."""
        if key in self._keys:
            return False
        if len(self._keys) >= self._limit:
            self._keys.clear()
        self._keys.add(key)
        return True

    @synchronized
    def forget(self, key: str) -> None:
        """Let ``key`` be reported again, because whatever was wrong with it is solved."""
        self._keys.discard(key)
