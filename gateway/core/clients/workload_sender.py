"""Sender that mirrors a stored workload payload to the Runtime API. The outbox registers it as a channel in PR 2."""

import logging

from core.clients.service_functional_role_client import ServiceFunctionalRoleClient
from core.ibm_cloud.sender import Sender
from core.services.best_effort_executor import submit_best_effort

logger = logging.getLogger("gateway.clients.workload_sender")


class WorkloadSender(Sender):
    """Delivers a workload envelope with a ServiceFunctionalRoleClient, one HTTP call per message. The client always
    uses the ``workloads.mirror.timeout_ms`` config as its request timeout; the ``timeout`` argument of ``send`` is only
    a switch. With timeout > 0, ``send`` calls the client in the caller's thread and raises RuntimeApiError on failure.
    With timeout=0 (best effort) it hands the call to the shared best-effort pool and returns at once, never raising:
    the request runs in the background, a failure is logged, and if the pool is full the update is dropped."""

    def __init__(self, client: ServiceFunctionalRoleClient | None = None) -> None:
        self._client = client or ServiceFunctionalRoleClient()

    def send(self, payload: dict, timeout: float = 5) -> None:
        if timeout > 0:
            self._client.put_function(payload)
            return
        try:
            submit_best_effort(self._send_best_effort, payload)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.warning("function_id=%s workload dropped: %r", payload.get("function_id"), exc)

    def _send_best_effort(self, payload: dict) -> None:
        try:
            self._client.put_function(payload)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.warning("function_id=%s workload dropped: %r", payload.get("function_id"), exc)
