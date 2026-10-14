"""Exceptions raised by the IBM Cloud integration."""


class CloudServiceUnavailableError(Exception):
    """An IBM Cloud service answered 429 or 5xx, or the connection failed, so the call can be retried."""
