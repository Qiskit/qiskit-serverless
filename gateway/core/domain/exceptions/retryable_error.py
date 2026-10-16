"""The error that says trying again can fix it."""


class RetryableError(Exception):
    """A call failed in a way a later try can fix: a timeout, a 429, a 5xx, a network error, or a problem of our own
    configuration (a missing or malformed key) that is fixed without losing the work.

    The outbox looks for it: a sender that raises it gets its row sent again later, and any other exception makes the
    outbox park the row. ``status_code`` is the HTTP status of the answer, when there was one."""

    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code
