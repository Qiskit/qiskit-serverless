"""Contract for whatever delivers an outbox payload to its destination."""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass

logger = logging.getLogger("gateway.ibm_cloud.sender")


@dataclass(frozen=True)
class PendingMessage:
    """A payload waiting to be delivered, plus the key the caller uses to learn whether it was."""

    key: int
    payload: dict


class Sender(ABC):
    """Delivers payloads to their destination."""

    @abstractmethod
    def send(self, payload: dict, timeout: float = 5) -> None:
        """Deliver the payload, waiting up to `timeout` seconds for the destination to confirm it. Raises on
        failure. With timeout=0 it does not wait and does not raise: the payload is handed over and the call
        returns, and a payload that is not delivered is dropped and only logged."""

    def flush(self, timeout: float = 5) -> None:
        """Wait up to `timeout` seconds, in total, for what send(timeout=0) handed over and is still pending.
        Meant for shutdown. A sender that delivers before send() returns has nothing to wait for."""

    def send_batch(self, messages: list[PendingMessage]) -> set[int]:
        """Deliver many messages and return the keys of the ones that were delivered. Never raises:
        a key missing from the result was not delivered and the caller must keep it for a retry.
        This default sends one by one; a sender that can confirm many at once should override it."""
        delivered: set[int] = set()
        for message in messages:
            try:
                self.send(message.payload)
            except Exception as ex:  # pylint: disable=broad-exception-caught
                logger.error("key=%s error sending: %s", message.key, str(ex))
                continue
            delivered.add(message.key)
        return delivered
