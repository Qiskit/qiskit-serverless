"""Sender that mirrors a stored workload payload to NTC. The outbox registers it as a channel in PR 2."""

import logging

from core.clients.runtime_api_client import RuntimeApiClient, RuntimeApiError
from core.ibm_cloud.sender import Sender

logger = logging.getLogger("gateway.clients.workload_sender")


class WorkloadSender(Sender):
    """Delivers a workload envelope with a RuntimeApiClient, one HTTP call per message. ``send`` raises
    RuntimeApiError on failure, except with timeout=0 (best effort): then it logs the error, drops the payload and
    returns without raising."""

    def __init__(self, client: RuntimeApiClient | None = None) -> None:
        self._client = client or RuntimeApiClient()

    def send(self, payload: dict, timeout: float = 5) -> None:
        if timeout > 0:
            self._client.put_function(payload, timeout=timeout)
            return
        try:
            self._client.put_function(payload)
        except RuntimeApiError as exc:
            logger.warning("function_id=%s workload dropped: %s", payload.get("function_id"), exc)
