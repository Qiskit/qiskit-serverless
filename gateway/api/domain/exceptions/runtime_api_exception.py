"""Runtime function exceptions."""


class RuntimeApiException(Exception):
    """Error in Runtime API"""

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class RuntimeFunctionsException(RuntimeApiException):
    """Error in Runtime API /entitlements"""


class RuntimeFunctionsUnavailable(RuntimeFunctionsException):
    """The Runtime API /entitlements call could not be completed because the service
    was unreachable or returned a server error.

    A subclass of :class:`RuntimeFunctionsException` so existing handlers still catch
    it, but distinguishable so a transient backend failure can be surfaced as a retry
    instead of an access denial."""
