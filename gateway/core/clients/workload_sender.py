"""Sender that mirrors a stored workload payload to NTC. The outbox registers it as a channel in PR 2."""

import logging

from core.clients.runtime_api_client import RuntimeApiClient, RuntimeApiError
from core.ibm_cloud.sender import Sender

logger = logging.getLogger("gateway.clients.workload_sender")


class WorkloadSender(Sender):
    """Delivers a workload envelope with a RuntimeApiClient, one HTTP call per message. The client always uses
    ``settings.WORKLOADS_MIRROR_TIMEOUT`` as its request timeout; the ``timeout`` argument of ``send`` is only a
    switch. With timeout > 0, ``send`` raises RuntimeApiError on failure. With timeout=0 (best effort) it never
    raises: it logs the error, drops the payload and returns."""

    def __init__(self, client: RuntimeApiClient | None = None) -> None:
        self._client = client or RuntimeApiClient()

    def send(self, payload: dict, timeout: float = 5) -> None:
        if timeout > 0:
            self._client.put_function(payload)
            return
        try:
            self._client.put_function(payload)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.warning("function_id=%s workload dropped: %r", payload.get("function_id"), exc)
