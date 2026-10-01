"""Contract for whatever delivers an outbox payload to its destination."""

from abc import ABC, abstractmethod


class Sender(ABC):
    """Delivers one payload to its destination."""

    @abstractmethod
    def send(self, payload: dict) -> None:
        """Deliver the payload."""
