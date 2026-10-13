"""Service unavailable exception."""

from rest_framework import status
from rest_framework.exceptions import APIException


class ServiceUnavailable(APIException):
    """A dependency needed to serve the request was unreachable or failing.

    Raised instead of an authentication error when the failure is a transient
    backend problem (a timeout, a connection error, or a 5xx from IBM Cloud),
    so the caller is told to retry rather than to fix credentials that are fine.
    """

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = (
        "We couldn't verify your access to Qiskit Functions at this time. "
        "Please try again later, or contact IBM support if the problem persists."
    )
    default_code = "service_unavailable"
