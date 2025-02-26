"""Interface to implement new services against the user will authenticate"""

from abc import ABC, abstractmethod
from typing import List


class AuthenticationBase(ABC):
    """
    Interface that declares three mandatory methods for the
    authentication process:
    - authenticate
    - verify_access
    - get_groups
    """

    @abstractmethod
    def authenticate(self) -> str | None:
        """This method authenticates the user and returns the user id."""

    @abstractmethod
    def verify_access(self) -> bool:
        """This method verifies if the user has access to Qiskit Functions."""

    @abstractmethod
    def get_groups(self) -> List[str]:
        """This method returns the current groups of the user."""
