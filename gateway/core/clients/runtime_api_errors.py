"""Errors shared by every client of the Runtime API. A failure that a later try can fix is a
``core.domain.exceptions.retryable_error.RetryableError`` instead."""

from core.domain.exceptions.retryable_error import RetryableError


class RuntimeApiError(Exception):
    """The Runtime API call failed and cannot be retried: the credential is missing, malformed, or rejected by IAM"""

    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class ResponseLostError(RetryableError):
    """The request was sent but no answer arrived (a read timeout, or the connection dropped), so the Runtime API
    may have applied it. A request that failed before it left, or that got an answer, is a plain RetryableError."""
