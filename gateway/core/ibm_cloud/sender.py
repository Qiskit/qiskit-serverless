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

    def group_key(self, payload: dict) -> str | None:  # pylint: disable=unused-argument
        """Name of the independent destination this payload goes to (a Kafka region, say). The caller
        sends and tracks failures per group, so one unreachable destination does not hold back the
        others. This default puts everything in one group."""
        return None
