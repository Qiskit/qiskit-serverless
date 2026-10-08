"""Errors shared by every client of the Runtime API.

The type says what a caller can do. Catch the two permanent subclasses first, ``RuntimeApiConfigError`` and
``RuntimeApiRejectedError``: sending the same thing again cannot succeed. Then catch the base class
``RuntimeApiError``, which is what is raised directly for a transient failure that may succeed later.
"""


class RuntimeApiError(Exception):
    """The Runtime API call failed. Raised directly, it is a transient failure (a 5xx, 408 or 429 status, a network
    error, an IAM failure other than a rejected key), so trying again later can succeed. It is also the base class of
    the permanent errors below."""

    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class RuntimeApiConfigError(RuntimeApiError):
    """Permanent: the deployment is not configured for the call (credential missing, malformed or rejected by IAM).
    Retrying cannot fix it."""

    def __init__(self, message: str):
        super().__init__(message)


class RuntimeApiRejectedError(RuntimeApiError):
    """Permanent: the Runtime API answered with a 4xx other than 408 or 429, so sending the same payload again cannot
    succeed (invalid payload, unknown instance)."""

    def __init__(self, message: str, *, status_code: int):
        super().__init__(message, status_code=status_code)
