"""Exceptions raised by the IBM Cloud integration."""


class CloudServiceUnavailableError(Exception):
    """An IBM Cloud service answered 429 or 5xx, or did not answer in time, so the call can be retried."""
