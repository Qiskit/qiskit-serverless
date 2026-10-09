"""Errors shared by every client of the Runtime API."""


class RuntimeApiError(Exception):
    """The Runtime API call failed and cannot be retried: the credential is missing, malformed, or rejected by IAM"""

    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class RuntimeApiRetryableError(RuntimeApiError):
    """The Runtime API call failed, and trying again can fix: 401, 403, 408, 429, 5xx, or network error"""
