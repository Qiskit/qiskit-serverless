"""Errors shared by every client of the Runtime API."""


class RuntimeApiError(Exception):
    """The Runtime API call failed. ``retryable`` is True when trying again later can succeed."""

    def __init__(self, message: str, *, retryable: bool, status_code: int | None = None):
        super().__init__(message)
        self.retryable = retryable
        self.status_code = status_code


class RuntimeApiConfigError(RuntimeApiError):
    """The deployment is not configured for the call (missing or rejected credential). Retrying cannot fix it."""

    def __init__(self, message: str):
        super().__init__(message, retryable=False)
