"""Errors shared by every client of the Runtime API. A failure that a later try can fix is a
``core.domain.exceptions.retryable_error.RetryableError`` instead."""


class RuntimeApiError(Exception):
    """The Runtime API call failed and cannot be retried: the credential is missing, malformed, or rejected by IAM"""

    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code
