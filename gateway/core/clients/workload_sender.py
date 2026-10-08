"""Sender that mirrors a stored workload payload to NTC. The outbox registers it as a channel in PR 2."""

from core.clients.runtime_api_client import RuntimeApiClient
from core.ibm_cloud.sender import Sender


class WorkloadSender(Sender):
    """Delivers a workload envelope with a RuntimeApiClient. ``send`` raises RuntimeApiError on failure, and
    ``send_batch`` (inherited) turns that into "not delivered, keep it for a retry"."""

    def __init__(self, client: RuntimeApiClient | None = None) -> None:
        self._client = client or RuntimeApiClient()

    def send(self, payload: dict) -> None:
        self._client.put_function(payload)
