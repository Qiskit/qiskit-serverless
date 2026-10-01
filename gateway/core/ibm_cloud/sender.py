"""Contract for whatever delivers an outbox payload to its destination."""

import logging
from abc import ABC, abstractmethod

logger = logging.getLogger("gateway.ibm_cloud.sender")


class Sender(ABC):
    """Delivers payloads to their destination."""

    @abstractmethod
    def send(self, payload: dict) -> None:
        """Deliver the payload. Raises on failure."""

    def send_batch(self, items: list[tuple[int, dict]]) -> set[int]:
        """Deliver many (key, payload) pairs and return the keys that were delivered. Never raises:
        a key missing from the result was not delivered and the caller must keep it for a retry.
        This default sends one by one; a sender that can confirm many at once should override it."""
        delivered: set[int] = set()
        for key, payload in items:
            try:
                self.send(payload)
            except Exception as ex:  # pylint: disable=broad-exception-caught
                logger.error("key=%s error sending: %s", key, str(ex))
                continue
            delivered.add(key)
        return delivered
