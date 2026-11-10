"""Decorator for the methods of an object that several threads share."""

import functools


def synchronized(method):
    """Run the method holding ``self._lock``. The lock is not reentrant: a synchronized method must not call another.

    A method that reads a Config entry must not be synchronized, because that read can reach the database and the
    lock would be held for the whole query. Read the entry first, then call a synchronized method with the value.
    """

    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:  # pylint: disable=protected-access
            return method(self, *args, **kwargs)

    return wrapper
