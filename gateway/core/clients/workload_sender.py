"""Outbox sender that mirrors a stored workload payload to the Runtime API."""

from core.clients.functions_operator_client import get_functions_operator_client
from core.ibm_cloud.sender import Sender


class WorkloadSender(Sender):
    """Sends the ``{"function_id", "body"}`` envelope that ``build_workload_payload`` stored in the outbox. It raises
    ``RuntimeApiError`` when the Runtime API does not take it, and the outbox keeps the row for a later try. The client
    is looked up on every send, so a missing or malformed key fails the send instead of the scheduler boot."""

    def send(self, payload: dict, timeout: float = 3) -> None:
        """``timeout`` (seconds, greater than zero) bounds the PUT. The ``timeout=0`` of the contract, to hand over
        without waiting, is not supported by an HTTP call and raises ValueError."""
        if timeout <= 0:
            raise ValueError("WorkloadSender needs a timeout greater than zero")
        get_functions_operator_client().put_function(payload["function_id"], payload["body"], timeout=timeout)
