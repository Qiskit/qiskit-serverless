"""Contract for whatever delivers an outbox payload to its destination."""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class PendingMessage:
    """A payload waiting to be delivered, plus the key the caller uses to learn whether it was."""

    key: int
    payload: dict


class Sender(ABC):
    """Delivers payloads to their destination, one at a time."""

    @abstractmethod
    def send(self, payload: dict, timeout: float = 5) -> None:
        """Deliver the payload. Raises on failure, except with timeout=0: that only hands the payload over, so it
        returns at once, does not raise, and a payload that is not delivered is dropped and logged. What else
        `timeout` means depends on the implementation."""


class BatchSender(Sender):
    """
    A sender that can also deliver many payloads at once, confirming each one (Kafka: produce many, flush
    once, and learn from the delivery callbacks which arrived).

    The outbox sends its rows to these in batches, and to a plain Sender (an HTTP call per message, say) one by one.
    """

    @abstractmethod
    def send_batch(self, messages: list[PendingMessage]) -> set[int]:
        """Deliver many messages and return the keys of the ones that were delivered. Never raises:
        a key missing from the result was not delivered and the caller must keep it for a retry."""
