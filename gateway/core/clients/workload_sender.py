"""Outbox sender that mirrors a stored workload payload to the Runtime API."""

from core.clients.functions_operator_client import get_functions_operator_client
from core.clients.runtime_api_errors import RuntimeApiError
from core.domain.exceptions.retryable_error import RetryableError
from core.ibm_cloud.sender import Sender


class WorkloadSender(Sender):
    """Sends the ``{"function_id", "body"}`` envelope that ``build_workload_payload`` stored in the outbox. It raises
    ``RetryableError`` when a later try can work (a missing or malformed key included, that is fixed without losing the
    row) and a plain ``RuntimeApiError`` when the Runtime API answered with a status that trying again will not change
    (a 400 or 404): the outbox sends the first again later and parks the second. The client
    is looked up on every send, so a missing or malformed key fails the send instead of the scheduler boot."""

    def send(self, payload: dict, timeout: float = 3) -> None:
        """``timeout`` (seconds, greater than zero) bounds the PUT. The ``timeout=0`` of the contract, to hand over
        without waiting, is not supported by an HTTP call and raises ValueError."""
        if timeout <= 0:
            raise ValueError("WorkloadSender needs a timeout greater than zero")
        try:
            get_functions_operator_client().put_function(payload["function_id"], payload["body"], timeout=timeout)
        except RuntimeApiError as ex:
            if ex.status_code is None:  # no answer to blame the row for: the key, or a body without crn
                raise RetryableError(str(ex)) from ex
            raise
