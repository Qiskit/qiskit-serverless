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
    def send(self, payload: dict) -> None:
        """Deliver the payload. Raises on failure."""

    def send_best_effort(self, payload: dict) -> None:
        """Deliver the payload without caring about the outcome: never raises, and a failure is only logged.
        This default waits for send(); a sender that can hand the payload over without waiting should override it."""
        try:
            self.send(payload)
        except Exception as ex:  # pylint: disable=broad-exception-caught
            logger.error("error sending best effort payload, dropped: %s", str(ex))

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
