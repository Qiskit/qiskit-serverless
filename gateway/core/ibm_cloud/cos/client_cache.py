"""A cache of COS clients that builds each one once, however many threads ask for it at the same time."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Hashable
from typing import Generic, TypeVar

from core.synchronized import synchronized

T = TypeVar("T")


class CosClientCache(Generic[T]):
    """Keeps the client built for each key for ``ttl_seconds``, and builds a new one after that.

    Building a COS client costs network calls (the HMAC secret and the IAM token), and several scheduler loops ask
    for the same project together. So looking in the cache, building and storing are one step under one lock: two
    threads that ask for the same key at once build it once, and the second gets the first one's result.

    The lock is held while building, so every other ``get`` waits for it, hits included. A miss happens about once a
    minute per project, so that wait is rare.

    The cache does not know what a client is: ``get`` takes the function that builds it.
    """

    def __init__(self, ttl_seconds: float) -> None:
        self._ttl_seconds = ttl_seconds
        self._lock = threading.Lock()
        self._entries: dict[Hashable, tuple[T, float]] = {}

    @synchronized
    def get(self, key: Hashable, build: Callable[[], T]) -> T:
        """The cached client for ``key``, or the one ``build`` returns, which is stored.

        If ``build`` raises, nothing is stored and the error reaches the caller. The threads that were waiting for
        the same key then try to build it themselves, one after the other.
        """
        entry = self._entries.get(key)
        if entry and time.monotonic() - entry[1] < self._ttl_seconds:
            return entry[0]
        client = build()
        self._entries[key] = (client, time.monotonic())
        return client

    @synchronized
    def clear(self) -> None:
        """Drop every cached client."""
        self._entries.clear()
