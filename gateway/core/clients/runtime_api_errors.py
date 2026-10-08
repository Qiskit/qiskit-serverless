"""Errors shared by every client of the Runtime API.

``RuntimeApiError`` is the normal error and it is permanent: sending the same thing again cannot succeed.
``RuntimeApiRetryableError`` is its subclass for a transient failure. To retry, catch ``RuntimeApiRetryableError``
first and then ``RuntimeApiError``; a plain ``except RuntimeApiError`` catches every client failure.
"""


class RuntimeApiError(Exception):
    """The Runtime API call failed and trying again cannot help: the credential is missing, malformed or rejected by
    IAM, or the Runtime API answered with a 4xx other than 408 or 429 (invalid payload, unknown instance).
    ``status_code`` is set when the error comes from a response."""

    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class RuntimeApiRetryableError(RuntimeApiError):
    """The Runtime API call failed in a way that trying again later can fix: a 408, 429 or 5xx status, a network
    error, or an IAM token failure that is not a rejected key."""
