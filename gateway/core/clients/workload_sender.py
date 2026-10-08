"""Sender that mirrors a stored workload payload to the Runtime API. The outbox registers it as a channel in PR 2."""

import logging

from core.clients.service_functional_role_client import ServiceFunctionalRoleClient
from core.ibm_cloud.sender import Sender
from core.services.background_executor import BackgroundExecutor

logger = logging.getLogger("gateway.clients.workload_sender")


class WorkloadSender(Sender):
    """Delivers a workload envelope with a ServiceFunctionalRoleClient, one HTTP call per message. The client always
    uses the ``workloads.mirror.timeout_ms`` config as its request timeout; the ``timeout`` argument of ``send`` is only
    a switch. With timeout > 0, ``send`` calls the client in the caller's thread and raises RuntimeApiError on failure.
    With timeout=0 it hands the call to the background executor and returns at once: the request runs in the
    background, a failure is logged, and if the pool is full the update is dropped. The only thing ``send`` raises with
    timeout=0 is BackgroundExecutorNotInitializedError, a wiring bug: every process that sends must call
    ``BackgroundExecutor.init()`` at startup."""

    def __init__(self, client: ServiceFunctionalRoleClient | None = None) -> None:
        self._client = client or ServiceFunctionalRoleClient()

    def send(self, payload: dict, timeout: float = 5) -> None:
        if timeout > 0:
            self._client.put_function(payload)
            return
        BackgroundExecutor.submit(self._deliver_in_background, payload)

    def _deliver_in_background(self, payload: dict) -> None:
        try:
            self._client.put_function(payload)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.warning("function_id=%s workload dropped: %r", payload.get("function_id"), exc)
